"""Versioned, conservative phrase tags. No model, network, or abstract storage.

Title and title+abstract cohorts are separate. A missing input is NOT a negative
classification. Evidence consists only of dictionary phrases and field names.
"""
from __future__ import annotations
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import logging
from pathlib import Path
import re
import unicodedata
import paper_metadata

ROOT=Path(__file__).resolve().parents[1]
LOG=logging.getLogger('physics-pulse-lite')
BASES=('title','title_abstract')

def normalize(s):
    s=unicodedata.normalize('NFKD',str(s or '')).casefold()
    s=''.join(c for c in s if not unicodedata.combining(c))
    # TeX accents and spacing are not generally parsed; recognize common syntax.
    s=re.sub(r'\\["\'`^~]\{?([a-z])\}?',r'\1',s)
    return ' '.join(re.sub(r'[^\w]+',' ',s,flags=re.UNICODE).split())

@lru_cache(maxsize=1)
def rules():
    d=json.loads((ROOT/'scripts/themes.json').read_text('utf-8'))
    d['fingerprint']=hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=True).encode()).hexdigest()[:16]
    d['ruleKey']=d['version']+'+'+d['fingerprint']
    ids=[t['id'] for t in d['themes']]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate theme ID')
    for t in d['themes']:
        if t.get('parent') and t['parent'] not in ids:raise ValueError('Unknown parent')
    return d

@lru_cache(maxsize=1)
def compiled():
    result=[]
    for t in rules()['themes']:
        seen=set();patterns=[]
        for a in t['aliases']:
            n=normalize(a)
            if n not in seen:patterns.append((a,re.compile(r'(?<!\w)'+re.escape(n)+r'(?!\w)')));seen.add(n)
        result.append((t,patterns))
    return result

def classify(title,abstract=None):
    """Returns no record for unavailable input; no opaque confidence score."""
    title=paper_metadata.text(title);abstract=paper_metadata.text(abstract)
    if not title:return {}
    fields={'title':normalize(title)}
    if abstract:fields['abstract']=normalize(abstract)
    direct={}
    for t,patterns in compiled():
        hits=[]
        for a,rx in patterns:
            for field,value in fields.items():
                if rx.search(value):hits.append({'field':field,'phrase':a})
        if hits:direct[t['id']]=hits
    # Parent membership is a union, never an addition of children counts.
    result={}
    for basis in BASES:
        if basis=='title_abstract' and not abstract:continue
        hits={k:[h for h in v if basis=='title_abstract' or h['field']=='title'] for k,v in direct.items()}
        hits={k:v for k,v in hits.items() if v}
        for t in rules()['themes']:
            if t.get('parent') and t['id'] in hits:
                parent=hits.setdefault(t['parent'],[])
                for h in hits[t['id']]:
                    if h not in parent:parent.append(h)
        material=title if basis=='title' else title+'\n'+abstract
        result[basis]={'hits':hits,'inputHash':hashlib.sha256(material.encode()).hexdigest(),
                       'titleHash':hashlib.sha256(title.encode()).hexdigest()}
    return result

def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS theme_classifications(
        id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
        rule_key TEXT NOT NULL,basis TEXT NOT NULL CHECK(basis IN ('title','title_abstract')),
        input_hash TEXT NOT NULL,title_hash TEXT NOT NULL,hits TEXT NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('saved','observed','observed-no-abstract')),
        PRIMARY KEY(id,rule_key,basis)) WITHOUT ROWID''')

def store(db,id,observations,source='saved'):
    title_obs=observations.get('title')
    if title_obs:
        # Do not keep abstract-derived tags attached to a replaced title.
        db.execute('DELETE FROM theme_classifications WHERE id=? AND title_hash<>?',(id,title_obs['titleHash']))
    for basis,result in observations.items():
        if basis not in BASES:raise ValueError('Invalid theme input basis')
        db.execute('''INSERT INTO theme_classifications VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(id,rule_key,basis) DO UPDATE SET input_hash=excluded.input_hash,
            title_hash=excluded.title_hash,hits=excluded.hits,source=excluded.source''',
            (id,rules()['ruleKey'],basis,result['inputHash'],result['titleHash'],json.dumps(result['hits'],ensure_ascii=True,separators=(',',':')),source))

def observe(db,p):
    if not p['category'].startswith('cond-mat.'):
        db.execute('DELETE FROM theme_classifications WHERE id=?',(p['id'],));return
    obs=p.get('_themes')
    if obs is None:
        obs=classify(p.get('title'))
    else:
        # An actual new response replaces that record's current abstract tags,
        # including removal if the upstream abstract is now empty.
        db.execute('DELETE FROM theme_classifications WHERE id=?',(p['id'],))
    source='observed-no-abstract' if '_themes' in p and 'title_abstract' not in obs else 'observed'
    store(db,p['id'],obs,source)

def backfill(db):
    """Read only available local inputs, once per rules hash/input fingerprint.

    Old-version tags without retained source text are dropped, not blended.
    Counts and sync checkpoints are never touched. Incoming observed tags take
    precedence over older restored abstracts with the same title.
    """
    current=rules()['ruleKey'];checked=updated=0
    with db:
        db.execute('DELETE FROM theme_classifications WHERE rule_key<>?',(current,))
        db.execute("DELETE FROM theme_classifications WHERE id IN (SELECT id FROM papers WHERE category NOT LIKE 'cond-mat.%')")
        query='''SELECT p.id,COALESCE(d.title,t.title) AS title,d.abstract_gz
          FROM papers p LEFT JOIN paper_details d ON p.id=d.id
          LEFT JOIN recent_titles t ON p.id=t.id WHERE p.category LIKE 'cond-mat.%' ORDER BY p.id'''
        for row in db.execute(query):
            title=paper_metadata.text(row['title'])
            if not title:continue
            checked+=1;th=hashlib.sha256(title.encode()).hexdigest()
            old={r['basis']:r for r in db.execute('SELECT * FROM theme_classifications WHERE id=? AND rule_key=?',(row['id'],current))}
            title_ok=old.get('title') is not None and old['title']['title_hash']==th
            rich_ok=old.get('title_abstract') is not None and old['title_abstract']['title_hash']==th
            if title_ok and (rich_ok or not row['abstract_gz'] or old['title']['source']=='observed-no-abstract'):continue
            abstract=paper_metadata.unpack_abstract(row['abstract_gz']) if row['abstract_gz'] and not rich_ok else None
            results=classify(title,abstract)
            store(db,row['id'],results,'saved');updated+=1
    LOG.info('Theme classification %s: %s titles available, %s records evaluated; no network.',rules()['version'],checked,updated)
    return {'checked':checked,'updated':updated,'ruleKey':current}

def metadata():
    r=rules()
    return {'schemaVersion':1,'ruleVersion':r['version'],'ruleKey':r['ruleKey'],'scope':'cond-mat',
      'engine':r['engine'],'facets':r['facets'],'definitions':r['themes'],'policy':r['policy'],
      'sources':r['sources'],'denominator':'eligible-inputs','multiLabel':True,
      'notice':'Independent lexical pilot; not author-assigned tags. Missing input is not absence. Rates refer to eligible records, not an estimate for missing records.'}

def summary(db,snapshot):
    """Aggregate from deduplicated record tags, including an unmatched bucket."""
    out=metadata();n=len(snapshot['monthStarts']);indices={x[:7]:i for i,x in enumerate(snapshot['monthStarts'])}
    total=[sum(c['counts'][i] for c in snapshot['categories'] if c['group']=='cond-mat') for i in range(n)]
    out['totals']=total;out['basis']={};out['files']={};out['paperIndexEnabled']=snapshot['paperIndexEnabled']
    for basis in BASES:
        out['basis'][basis]={'eligible':[0]*n,'unmatched':[0]*n,'hits':{t['id']:[0]*n for t in rules()['themes']}}
    for row in db.execute('''SELECT c.basis,c.hits,strftime('%Y-%m',p.created,'unixepoch') AS month
        FROM theme_classifications c JOIN papers p ON p.id=c.id
        WHERE c.rule_key=? AND p.category LIKE 'cond-mat.%' AND p.created<? ''',(rules()['ruleKey'],__import__('oai').utc_datetime(snapshot['asOf']).timestamp())):
        i=indices.get(row['month'])
        if i is None:continue
        b=out['basis'][row['basis']];b['eligible'][i]+=1;hits=json.loads(row['hits'])
        if not hits:b['unmatched'][i]+=1
        for id in hits:
            if id not in b['hits']:raise ValueError('Unknown theme tag')
            b['hits'][id][i]+=1
    for b in out['basis'].values():
        if any(e>t for e,t in zip(b['eligible'],total)):raise ValueError('Theme inputs exceed corpus counts')
    return out

def month_index(db,start,end):
    """No abstracts/titles duplicated here; UI joins existing monthly shards."""
    from oai import utc_datetime
    lo=int(utc_datetime(start+'T00:00:00Z').timestamp());hi=int(end.timestamp())
    records={}
    for row in db.execute('''SELECT p.id,p.category,c.basis,c.hits FROM papers p
      JOIN theme_classifications c ON c.id=p.id WHERE p.created>=? AND p.created<?
      AND p.category LIKE 'cond-mat.%' AND c.rule_key=? ORDER BY p.id,c.basis''',(lo,hi,rules()['ruleKey'])):
        r=records.setdefault(row['id'],{'id':row['id'],'category':row['category'],'basis':{}})
        r['basis'][row['basis']]=json.loads(row['hits'])
    return {'schemaVersion':1,'month':start,'ruleKey':rules()['ruleKey'],'records':list(records.values())}
