#!/usr/bin/env python3
"""Reject DEMO, stale manifests, unsafe paths and broken public paper indices."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
import update_data as m
import themes
import hashlib

MAX_SITE_BYTES=900*1024*1024


def validate(site: Path, *, allow_stale: bool=False) -> dict:
    index=site/'data/physics.json'
    data=json.loads(index.read_text('utf-8'))
    if data.get('mode')!='live' or data.get('period')!='month' or data.get('schemaVersion')!=3:
        raise m.HarvestError('Production deployment requires LIVE monthly data; refusing to publish a demo.')
    if not data.get('coverage',{}).get('complete'):raise m.HarvestError('Incomplete metadata harvest.')
    dates=data.get('monthStarts',[])
    if len(dates)!=60:raise m.HarvestError('Production requires 60 verified months.')
    asof=m.utc_datetime(data['asOf'])
    expected=[m.shift_month(asof,i-59).date().isoformat() for i in range(60)]
    if dates!=expected:raise m.HarvestError('Noncontiguous monthly series.')
    age=(datetime.now(timezone.utc)-asof).total_seconds()
    if age < -86400:raise m.HarvestError('Future snapshot is not valid.')
    if not allow_stale and age>3*86400:raise m.HarvestError('Snapshot is more than 3 days old; refusing to mark it newly updated.')
    refs=set();papers=0;indexed={}
    for i,month in enumerate(dates):
        mapping=data.get('paperFiles',{}).get(month,{})
        for cat in data['categories']:
            count=cat['counts'][i]
            if type(count)!=int or count<0:raise m.HarvestError('Invalid paper count.')
            if not data.get('paperIndexEnabled'):continue
            rel=mapping.get(cat['id'])
            if not count:
                if rel:raise m.HarvestError('Unexpected nonempty index for a zero count.')
                continue
            if not isinstance(rel,str) or not re.fullmatch(r'data/papers/[0-9]{4}-[0-9]{2}-01/[A-Za-z0-9.-]+-[0-9a-f]{12}\.json\.gz',rel):
                raise m.HarvestError('Missing or unsafe paper index path.')
            p=site/rel
            if p.is_symlink() or not p.is_file():raise m.HarvestError('Missing paper index.')
            with gzip.open(p,'rt',encoding='utf-8') as f:body=json.load(f)
            if body.get('month')!=month or body.get('category')!=cat['id'] or len(body.get('papers',[]))!=count:
                raise m.HarvestError('Paper index and count series disagree.')
            ids=set();lo=m.epoch(m.utc_datetime(month+'T00:00:00Z'));hi=m.epoch(min(m.shift_month(m.utc_datetime(month+'T00:00:00Z'),1),asof))
            for row in body['papers']:
                if not isinstance(row,list) or not 2<=len(row)<=5 or not lo<=row[1]<hi or row[0] in ids:
                    raise m.HarvestError('Invalid or duplicate indexed paper.')
                ids.add(row[0])
            indexed[(month,cat['id'])]=ids
            refs.add(rel);papers+=count
    refs.update(validate_themes(site,data,indexed))
    files=[]
    for p in site.rglob('*'):
        if p.is_symlink():raise m.HarvestError('Symlinks cannot enter the public deployment.')
        if not p.is_file():continue
        rel=p.relative_to(site).as_posix();files.append(p)
        if '.sqlite' in p.name or p.name.startswith('.env') or p.suffix=='.xml':raise m.HarvestError('Private/raw data found in public directory.')
        if rel.startswith(('data/papers/','data/themes/')) and rel not in refs:raise m.HarvestError('Expired or orphaned paper index remains in public directory.')
        if rel not in refs and rel not in ('index.html','data/physics.json','health.json','robots.txt','.nojekyll'):
            raise m.HarvestError('Unexpected public file; review explicitly: '+rel)
    if not (site/'index.html').is_file():raise m.HarvestError('HTML was not built.')
    page=(site/'index.html').read_text('utf-8')
    if '"mode":"demo"' in page:raise m.HarvestError('HTML embeds demo data.')
    if data['asOf'] not in page:raise m.HarvestError('HTML and JSON snapshot differ.')
    size=sum(p.stat().st_size for p in files)
    if size>MAX_SITE_BYTES:raise m.HarvestError('Static site exceeds the 900 MiB safety limit.')
    return {'asOf':data['asOf'],'visibleMonths':60,'papers':papers,'files':len(files),'bytes':size,'mode':'live','appVersion':'0.6.0'}


def validate_themes(site,data,indexed):
    t=data.get('themes')
    if t is None:return set()  # old snapshots remain readable before local rebuild
    if t.get('schemaVersion')!=1 or t.get('ruleKey')!=themes.rules()['ruleKey']:
        raise m.HarvestError('Theme rule-version mismatch.')
    if t.get('definitions')!=themes.rules()['themes'] or t.get('policy')!=themes.rules()['policy']:
        raise m.HarvestError('Theme definitions do not match the frozen rules.')
    n=len(data['monthStarts']);refs=set();ids={x['id'] for x in t['definitions']}
    if t.get('totals')!=[sum(c['counts'][i] for c in data['categories'] if c['group']=='cond-mat') for i in range(n)]:
        raise m.HarvestError('Theme corpus denominator mismatch.')
    if set(t.get('basis',{}))!=set(themes.BASES):raise m.HarvestError('Missing theme input cohort.')
    for b in t['basis'].values():
        if set(b.get('hits',{}))!=ids:raise m.HarvestError('Unknown theme.')
        series=[b['eligible'],b['unmatched'],*b['hits'].values()]
        if any(len(x)!=n or any(type(v)!=int or v<0 for v in x) for x in series):raise m.HarvestError('Invalid theme series.')
        if any(e>all_ for e,all_ in zip(b['eligible'],t['totals'])):raise m.HarvestError('Theme coverage exceeds corpus.')
        for x in [b['unmatched'],*b['hits'].values()]:
            if any(a>e for a,e in zip(x,b['eligible'])):raise m.HarvestError('Theme hits exceed evaluated inputs.')
    if not data['paperIndexEnabled']:
        if t['files']:raise m.HarvestError('Unexpected theme index in counts-only mode.')
        return refs
    for i,key in enumerate(data['monthStarts']):
        rel=t['files'].get(key)
        if not isinstance(rel,str) or not re.fullmatch(r'data/themes/[0-9]{4}-[0-9]{2}-01-[0-9a-f]{12}\.json\.gz',rel):
            raise m.HarvestError('Unsafe/missing theme index.')
        path=site/rel
        if path.is_symlink() or not path.is_file():raise m.HarvestError('Missing theme index.')
        with gzip.open(path,'rb') as f:raw=f.read()
        if hashlib.sha256(raw).hexdigest()[:12] not in path.name:raise m.HarvestError('Theme index checksum mismatch.')
        body=json.loads(raw)
        if body.get('schemaVersion')!=1 or body.get('month')!=key or body.get('ruleKey')!=t['ruleKey']:
            raise m.HarvestError('Theme index version mismatch.')
        seen=set();tallies={b:{'eligible':0,'unmatched':0,'hits':{id:0 for id in ids}} for b in themes.BASES}
        for row in body['records']:
            id=row['id'];cat=row['category']
            if id in seen or not cat.startswith('cond-mat.') or id not in indexed.get((key,cat),set()):
                raise m.HarvestError('Unknown or duplicate theme paper.')
            seen.add(id)
            if not row['basis'] or not set(row['basis'])<=set(themes.BASES):raise m.HarvestError('Invalid theme basis.')
            for basis,hits in row['basis'].items():
                v=tallies[basis];v['eligible']+=1;v['unmatched']+=not bool(hits)
                if not set(hits)<=ids:raise m.HarvestError('Unknown theme label.')
                for tag,evidence in hits.items():
                    if not evidence or any(set(e)!={'field','phrase'} or e['field'] not in ('title','abstract') or not isinstance(e['phrase'],str) or (basis=='title' and e['field']!='title') for e in evidence):
                        raise m.HarvestError('Invalid theme evidence.')
                    v['hits'][tag]+=1
        for basis,v in tallies.items():
            b=t['basis'][basis]
            if v['eligible']!=b['eligible'][i] or v['unmatched']!=b['unmatched'][i] or any(v['hits'][id]!=b['hits'][id][i] for id in ids):
                raise m.HarvestError('Theme counts and paper membership disagree.')
        refs.add(rel)
    return refs


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--site',type=Path,default=m.ROOT/'site');ap.add_argument('--allow-stale',action='store_true')
    a=ap.parse_args()
    try:print(json.dumps(validate(a.site,allow_stale=a.allow_stale)))
    except (m.HarvestError,OSError,ValueError,TypeError,KeyError) as exc:ap.exit(1,'Validation failed: '+str(exc)+'\n')

if __name__=='__main__':main()
