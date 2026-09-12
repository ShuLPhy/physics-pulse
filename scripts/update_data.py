#!/usr/bin/env python3
"""Physics Pulse 0.6.0: monthly counts with optional bibliographic metadata.

Core count/sync storage stays at .cache/physics-lite.sqlite. Normal incremental
updates keep received titles/authors, but still discard incoming abstracts.
--local-only --restore-metadata reuses the old local DB without any download.
Only restored abstracts are kept, gzip-compressed, in a separate detail table.
"""
from __future__ import annotations
import argparse
import contextlib
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import urllib.parse
from typing import Any
import paper_metadata
import themes
from oai import SerialHTTP, HarvestError, OAIError, parse_oai, utc_datetime, stamp, OAI_URL

ROOT=Path(__file__).resolve().parents[1]
UTC=timezone.utc
LOG=logging.getLogger('physics-pulse-lite')


def month_start(dt):
    return dt.astimezone(UTC).replace(day=1,hour=0,minute=0,second=0,microsecond=0)


def shift_month(dt,n):
    dt=month_start(dt);y,m=divmod(dt.year*12+dt.month-1+n,12)
    return dt.replace(year=y,month=m+1)


def epoch(dt):return int(dt.timestamp())


def retention_start(as_of,months):return shift_month(as_of,-months)


def comparison_window(as_of):
    current=month_start(as_of);previous=shift_month(as_of,-1)
    elapsed=as_of-current;common=min(elapsed,current-previous)
    return {'currentStart':stamp(current),'currentEndExclusive':stamp(current+common),
            'previousStart':stamp(previous),'previousEndExclusive':stamp(previous+common),
            'commonDurationSeconds':int(common.total_seconds()),'cappedToShorterMonth':common<elapsed}


def connect_db(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA journal_mode=WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS papers(
          id TEXT PRIMARY KEY,created INTEGER NOT NULL,category TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE INDEX IF NOT EXISTS papers_time ON papers(created);
        CREATE INDEX IF NOT EXISTS papers_category_time ON papers(category,created);
        CREATE TABLE IF NOT EXISTS recent_titles(
          id TEXT PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,title TEXT NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS harvest_seen(id TEXT PRIMARY KEY) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS monthly_baseline(
          month TEXT NOT NULL,category TEXT NOT NULL,n INTEGER NOT NULL CHECK(n>=0),
          PRIMARY KEY(month,category)
        ) WITHOUT ROWID;
    ''')
    cols=[r['name'] for r in db.execute('PRAGMA table_info(papers)')]
    if cols!=['id','created','category']:
        db.close();raise HarvestError('This is not a Lite database. Use a different --db path; old data are imported separately.')
    paper_metadata.initialize(db)
    themes.initialize(db)
    db.commit();return db


def get_meta(db,key):
    row=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def put_meta(db,key,value):
    db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))


@contextlib.contextmanager
def collector_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(str(path)+'.update.lock','a') as lock:
        try:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except ImportError as exc:raise HarvestError('Collector locking requires macOS/Linux.') from exc
        except BlockingIOError as exc:raise HarvestError('Another collector is using this database.') from exc
        yield


def migrate_legacy(db,legacy,site,as_of,months,title_months,local_only=False):
    """Copy ONLY minimal columns from v1/v2. The source remains untouched."""
    if get_meta(db,'legacy_import') or db.execute('SELECT COUNT(*) FROM papers').fetchone()[0] or not legacy.exists():return
    src=sqlite3.connect(legacy.resolve().as_uri()+'?mode=ro',uri=True);src.row_factory=sqlite3.Row
    try:
        src.execute('BEGIN')
        cols={r['name'] for r in src.execute('PRAGMA table_info(papers)')}
        if not {'id','published','primary_cat'}<=cols:raise HarvestError('Unrecognized legacy database; import stopped.')
        old={r['key']:json.loads(r['value']) for r in src.execute('SELECT key,value FROM meta')}
        cutoff=utc_datetime(old['snapshot_as_of']) if old.get('snapshot_as_of') else None
        import_asof=cutoff if local_only and cutoff else as_of
        minimum=retention_start(import_asof,months)
        title_min=shift_month(import_asof,1-title_months) if title_months else None
        allowed={c['id'] for c in json.loads((ROOT/'scripts/taxonomy.json').read_text('utf-8'))['categories']}
        total=0
        with db:
            # SQL selects exactly these columns; abstracts are never read into Python.
            for row in src.execute('SELECT id,published,primary_cat FROM papers'):
                dt=utc_datetime(row['published'])
                if dt>=minimum and row['primary_cat'] in allowed:
                    db.execute('INSERT OR REPLACE INTO papers VALUES (?,?,?)',(row['id'],epoch(dt),row['primary_cat']));total+=1
            if title_min is not None and 'title' in cols:
                for row in src.execute('SELECT id,title FROM papers WHERE published>=?',(stamp(title_min),)):
                    if db.execute('SELECT 1 FROM papers WHERE id=?',(row['id'],)).fetchone():
                        db.execute('INSERT OR REPLACE INTO recent_titles VALUES (?,?)',(row['id'],row['title']))
            lo=old.get('coverage_from')
            if lo and cutoff and old.get('last_success') and not old.get('checkpoint'):
                lo=max(utc_datetime(lo),minimum)
                with contextlib.suppress(OSError,ValueError,KeyError):
                    index=json.loads((site/'data/physics.json').read_text('utf-8'))
                    if index.get('mode')=='live' and index.get('coverage',{}).get('complete'):
                        lo=max(lo,utc_datetime(index['coverage']['from']))
                put_meta(db,'coverage_from',stamp(lo));put_meta(db,'snapshot_as_of',stamp(cutoff));put_meta(db,'last_success',old['last_success'])
            else:LOG.warning('Legacy harvest was not verified complete; a fresh synchronization is required.')
            put_meta(db,'legacy_import',{'source':str(legacy),'rows':total,'date':stamp(as_of)})
        LOG.info('Imported %s minimal rows. Original cache is unchanged: %s',f'{total:,}',legacy)
    finally:src.close()


def upsert_records(db,records,minimum,allowed,title_minimum=None):
    retained=0
    for p in records:
        if p.get('deleted'):
            db.execute('DELETE FROM papers WHERE id=?',(p['id'],));continue
        cat=p['category']
        if cat not in allowed and (cat.startswith(('physics.','cond-mat.','astro-ph.','nlin.','hep-','nucl-')) or cat in ('quant-ph','gr-qc','math-ph')):
            raise HarvestError(f'Unknown Physics category {cat}; update taxonomy before proceeding.')
        if cat not in allowed or p['created']<epoch(minimum):
            db.execute('DELETE FROM papers WHERE id=?',(p['id'],));continue
        db.execute('INSERT INTO papers VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET created=excluded.created,category=excluded.category',(p['id'],p['created'],cat))
        if title_minimum is not None and p['created']>=epoch(title_minimum) and p.get('title'):
            db.execute('INSERT INTO recent_titles VALUES (?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title',(p['id'],p['title']))
        else:db.execute('DELETE FROM recent_titles WHERE id=?',(p['id'],))
        if "authors" in p:paper_metadata.store_observed(db,p)
        themes.observe(db,p)
        retained+=1
    return retained


def harvest(db,tax,as_of,months,client,title_months=2,max_pages=10000,force=False,retain_bibliography=True,incremental_only=False):
    minimum=retention_start(as_of,months)
    lo=get_meta(db,'coverage_from');last=get_meta(db,'last_success')
    full=force or not last or not lo or utc_datetime(lo)>minimum
    cp=get_meta(db,'checkpoint')
    if incremental_only and (full or (cp and cp.get('set') == 'physics')):
        raise HarvestError('Full-window synchronization blocked. Restore a verified Lite seed; no requests were sent.')
    if force or cp and (cp.get('minimum')!=stamp(minimum) or cp.get('title_months')!=title_months):
        with db:db.execute("DELETE FROM meta WHERE key='checkpoint'")
        cp=None
    if cp:
        token=cp['token'];from_date=cp['from_date'];selected_set=cp['set'];cutoff=utc_datetime(cp['cutoff'])
        first_response=cp.get('first_response');LOG.info('Resuming committed pages; no incomplete snapshot is published.')
    else:
        from_date=(minimum if full else max(minimum,utc_datetime(last)-timedelta(days=2))).date().isoformat()
        selected_set='physics' if full else None;cutoff=as_of;token=None;first_response=None
        with db:db.execute('DELETE FROM harvest_seen')
    full=selected_set=='physics'
    title_min=shift_month(cutoff,1-title_months) if title_months else None
    allowed={c['id'] for c in tax['categories']};pages=processed=retained=0;restarted=False
    LOG.info('%s synchronization: %d visible months + one baseline month. Total pages are unknown.', 'Full-window' if full else 'Incremental', months)
    LOG.info('Keep core counts; bibliographic retention=%s, titles=%s. Incoming abstracts are discarded.',retain_bibliography,bool(title_months))
    while True:
        params={'verb':'ListRecords'}
        if token:params['resumptionToken']=token
        else:
            params.update(metadataPrefix='arXivRaw',**{'from':from_date})
            if selected_set:params['set']=selected_set
        try:page=parse_oai(client.request(OAI_URL+'?'+urllib.parse.urlencode(params)),title_min,author_minimum=minimum if retain_bibliography else None,
                           theme_minimum=minimum if retain_bibliography else None)
        except OAIError as exc:
            if exc.code=='badResumptionToken' and token and not restarted:
                token=None;restarted=True;first_response=None
                with db:db.execute('DELETE FROM harvest_seen')
                LOG.warning('Expired token; restarting the same range without duplicate IDs.');continue
            raise
        pages+=1;processed+=len(page['records'])
        with db:
            retained+=upsert_records(db,page['records'],minimum,allowed,title_min)
            if full:
                db.executemany('INSERT OR IGNORE INTO harvest_seen VALUES (?)',[(p['id'],) for p in page['records'] if not p.get('deleted') and p['category'] in allowed and p['created']>=epoch(minimum)])
            first_response=first_response or page['responseDate'];token=page['token']
            put_meta(db,'checkpoint',{'minimum':stamp(minimum),'title_months':title_months,'from_date':from_date,'set':selected_set,'token':token,'cutoff':stamp(cutoff),'first_response':first_response})
        LOG.info('Page %d: %s records processed; %s retained/upserted (not a distinct total).',pages,f'{processed:,}',f'{retained:,}')
        if not token:break
        if pages>=max_pages:raise HarvestError('Page limit reached. Checkpoint saved; rerun the same command.')
    with db:
        if full:db.execute('DELETE FROM papers WHERE id NOT IN (SELECT id FROM harvest_seen)')
        db.execute('DELETE FROM harvest_seen');db.execute('DELETE FROM papers WHERE created<?',(epoch(minimum),))
        if title_min is None:db.execute('DELETE FROM recent_titles')
        else:db.execute('DELETE FROM recent_titles WHERE id IN (SELECT id FROM papers WHERE created<?)',(epoch(title_min),))
        put_meta(db,'coverage_from',stamp(minimum));put_meta(db,'last_success',first_response or stamp(cutoff));put_meta(db,'snapshot_as_of',stamp(cutoff))
        db.execute("DELETE FROM meta WHERE key='checkpoint'")
    return {'complete':True,'from':stamp(minimum),'to':stamp(cutoff),'recordsProcessed':processed,'pages':pages,'fullWindow':full}


def local_coverage(db,requested):
    if get_meta(db,'checkpoint'):raise HarvestError('An unfinished harvest exists. Resume it before using --local-only.')
    lo=get_meta(db,'coverage_from');cutoff=get_meta(db,'snapshot_as_of')
    if not lo or not cutoff:raise HarvestError('No completed local coverage. Run without --local-only first.')
    as_of=utc_datetime(cutoff);minimum=utc_datetime(lo);months=requested
    while months>=2 and retention_start(as_of,months)<minimum:months-=1
    if months<2:raise HarvestError('Fewer than two monthly periods and their baseline are verified.')
    if months<requested:LOG.warning('Only %d/%d months are covered locally; missing months are not filled with zeros.',months,requested)
    return as_of,months,{'complete':True,'from':lo,'to':cutoff,'localOnly':True}


def aggregate(db,tax,as_of,months,coverage,title_months=2,paper_index=True):
    minimum=retention_start(as_of,months)
    if not coverage.get('complete') or utc_datetime(coverage['from'])>minimum or utc_datetime(coverage['to'])<as_of:
        raise HarvestError('Refusing to publish unverified monthly coverage.')
    starts=[shift_month(as_of,i-months+1) for i in range(months)]
    indices={d.strftime('%Y-%m'):i for i,d in enumerate(starts)}
    cats={c['id']:{**c,'counts':[0]*months,'baselinePreviousCount':0,'currentComparable':0,'previousComparable':0} for c in tax['categories']}
    for row in db.execute("SELECT category,strftime('%Y-%m',created,'unixepoch') AS month,COUNT(*) AS n FROM papers WHERE created>=? AND created<? GROUP BY category,month",(epoch(minimum),epoch(as_of))):
        if row['category'] not in cats:raise HarvestError('Unknown category in cache.')
        cat=cats[row['category']]
        if row['month'] in indices:cat['counts'][indices[row['month']]]=row['n']
        elif row['month']==minimum.strftime('%Y-%m'):cat['baselinePreviousCount']=row['n']
    saved_baseline=get_meta(db,'baseline_month')
    if saved_baseline==minimum.strftime('%Y-%m'):
        # These are frozen aggregate counts, not retained old paper records.
        for cat in cats.values():cat['baselinePreviousCount']=0
        for row in db.execute('SELECT category,n FROM monthly_baseline WHERE month=?',(saved_baseline,)):
            if row['category'] in cats:cats[row['category']]['baselinePreviousCount']=row['n']
    comp=comparison_window(as_of)
    for name,lo,hi in [('currentComparable',comp['currentStart'],comp['currentEndExclusive']),('previousComparable',comp['previousStart'],comp['previousEndExclusive'])]:
        for row in db.execute('SELECT category,COUNT(*) AS n FROM papers WHERE created>=? AND created<? GROUP BY category',(epoch(utc_datetime(lo)),epoch(utc_datetime(hi)))):
            cats[row['category']][name]=row['n']
    return {'schemaVersion':3,'period':'month','mode':'live','source':'arXiv OAI-PMH / arXivRaw v1 timestamp; minimal retained fields',
            'asOf':stamp(as_of),'generatedAt':stamp(datetime.now(UTC)),'timezone':'UTC','monthStarts':[d.date().isoformat() for d in starts],
            'defaultMonthIndex':months-1,'currentMonthIndex':months-1,'latestCompleteMonthIndex':months-2,'requestedMonths':months,
            'groups':tax['groups'],'categories':list(cats.values()),'comparison':comp,'coverage':coverage,
            'paperIndexEnabled':paper_index,'paperFiles':{},'titleMonths':title_months,
            'titlesSince':stamp(shift_month(as_of,1-title_months)) if title_months else None,
            'ranking':{'paperMetric':'saved_title_abstract_keyword_match','regionMetric':'three_month_share_change_pp','minimumPreviousCount':30},
            'storagePolicy':{'core':['id','created','category'],'abstracts':'restored-local-only','authors':'observed-or-restored','citations':False},
            'retention':{'visibleMonths':months,'individualRecordsFrom':stamp(shift_month(as_of,1-months)),
              'baseline':'one older month of frozen category counts only','rawResponses':'discard-after-parsing'},
            'metadataPolicy':{'abstractSource':'local-legacy-cache','networkBackfill':False,'missingFields':'unavailable','normalSync':'keep-received-title-authors'}}


def prune_monthly(db,as_of,months,tax,*,full_window=False):
    """Keep exactly `months` calendar months of individual records.

    Preserve only one older month's CATEGORY TOTALS for the oldest visible
    month's comparison. These totals are frozen after deleting the source IDs;
    subsequent reclassifications of that discarded month cannot be reconstructed.
    Never infer coverage from MIN(created): trust completed-harvest markers only.
    """
    if get_meta(db,'checkpoint'):
        raise HarvestError('Cannot rotate an incomplete harvest.')
    minimum=retention_start(as_of,months)
    first=shift_month(as_of,1-months)
    key=minimum.strftime('%Y-%m')
    previous=get_meta(db,'baseline_month')
    lo=get_meta(db,'coverage_from')
    if not lo or utc_datetime(lo)>minimum:
        raise HarvestError('Cannot rotate without verified baseline coverage.')
    rotated=previous!=key
    with db:
        if rotated or full_window:
            counts={r['category']:r['n'] for r in db.execute(
                'SELECT category,COUNT(*) AS n FROM papers WHERE created>=? AND created<? GROUP BY category',
                (epoch(minimum),epoch(first)))}
            db.execute('DELETE FROM monthly_baseline')
            db.executemany('INSERT INTO monthly_baseline VALUES (?,?,?)',
                [(key,c['id'],counts.get(c['id'],0)) for c in tax['categories']])
            put_meta(db,'baseline_month',key)
        n=db.execute('DELETE FROM papers WHERE created<?',(epoch(first),)).rowcount
        put_meta(db,'coverage_from',stamp(max(utc_datetime(lo),minimum)))
        put_meta(db,'retention_months',months)
        put_meta(db,'individual_records_from',stamp(first))
    LOG.info('Retention: %d calendar months from %s; deleted %s old paper records and their details.',months,first.date(),n)
    return {'rotated':rotated,'deletedPapers':n,'individualRecordsFrom':stamp(first),
            'baselineMonth':key,'baselineIsFrozen':True}


def json_text(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def atomic_write(path,content):
    path.parent.mkdir(parents=True,exist_ok=True)
    body=content.encode('utf-8') if isinstance(content,str) else content
    with tempfile.NamedTemporaryFile('wb',dir=path.parent,delete=False,prefix='.tmp-') as f:
        f.write(body);f.flush();os.fsync(f.fileno());temp=Path(f.name)
    try:os.replace(temp,path)
    finally:temp.unlink(missing_ok=True)


def publish(db,snapshot,site):
    if snapshot['mode']!='live' or not snapshot['coverage'].get('complete'):raise HarvestError('Only complete snapshots can be published.')
    as_of=utc_datetime(snapshot['asOf']);title_min=utc_datetime(snapshot['titlesSince']) if snapshot['titlesSince'] else None
    themes.backfill(db)
    snapshot['themes']=themes.summary(db,snapshot)
    keep=set(); theme_keep=set(); totals={'papers':0,'titles':0,'authors':0,'abstracts':0}
    snapshot['metadataCoverage']={}
    if snapshot['paperIndexEnabled']:
        for i,key in enumerate(snapshot['monthStarts']):
            start=utc_datetime(key+'T00:00:00Z');end=min(shift_month(start,1),as_of)
            mapping={};month_coverage={}
            for cat in snapshot['categories']:
                if not cat['counts'][i]:continue
                # Supplemental metadata never adds/removes a counted paper.
                rows=[];cov={'papers':0,'titles':0,'authors':0,'abstracts':0}
                query='''SELECT p.id,p.created,t.title AS recent_title,d.title,d.authors,d.abstract_gz
                    FROM papers p LEFT JOIN recent_titles t ON p.id=t.id
                    LEFT JOIN paper_details d ON p.id=d.id
                    WHERE p.category=? AND p.created>=? AND p.created<? ORDER BY p.created DESC,p.id DESC'''
                for r in db.execute(query,(cat['id'],epoch(start),epoch(end))):
                    title=r['title'] or (r['recent_title'] if title_min is not None and r['created']>=epoch(title_min) else None)
                    authors=r['authors'];abstract=paper_metadata.unpack_abstract(r['abstract_gz'])
                    row=[r['id'],r['created']]
                    if authors or abstract:row.extend([title,authors,abstract])
                    elif title:row.append(title)
                    rows.append(row)
                    cov['papers']+=1;cov['titles']+=bool(title);cov['authors']+=bool(authors);cov['abstracts']+=bool(abstract)
                if len(rows)!=cat['counts'][i]:raise HarvestError('Counts disagree with the paper index.')
                month_coverage[cat['id']]=cov
                for field in totals:totals[field]+=cov[field]
                schema=2 if any(len(row)>3 for row in rows) else 1
                payload=json_text({'schemaVersion':schema,'month':key,'category':cat['id'],'papers':rows,'metadataCoverage':cov})
                digest=hashlib.sha256(payload.encode()).hexdigest()[:12]
                rel=f'data/papers/{key}/{cat["id"]}-{digest}.json.gz'
                if not (site/rel).exists():atomic_write(site/rel,gzip.compress(payload.encode(),compresslevel=6,mtime=0))
                keep.add(rel);mapping[cat['id']]=rel
            snapshot['paperFiles'][key]=mapping
            snapshot['metadataCoverage'][key]=month_coverage
            LOG.info('Exported compact index %d/%d: %s.',i+1,len(snapshot['monthStarts']),key[:7])
    if snapshot['paperIndexEnabled']:
        for key in snapshot['monthStarts']:
            end=min(shift_month(utc_datetime(key+'T00:00:00Z'),1),as_of)
            body=json_text(themes.month_index(db,key,end))
            digest=hashlib.sha256(body.encode()).hexdigest()[:12]
            rel=f'data/themes/{key}-{digest}.json.gz'
            atomic_write(site/rel,gzip.compress(body.encode(),compresslevel=6,mtime=0))
            snapshot['themes']['files'][key]=rel;theme_keep.add(rel)
    snapshot['metadataTotals']=totals
    atomic_write(site/'data/physics.json',json_text(snapshot))
    # Remove superseded shards only after successfully replacing the manifest.
    # Old tabs must reload. The legacy LOCAL database remains untouched.
    for path in (site/'data/themes').glob('*.json.gz'):
        if path.relative_to(site).as_posix() not in theme_keep:path.unlink()
    root=site/'data/papers'
    for path in root.rglob('*'):
        if path.is_file() and path.name.endswith(('.json','.json.gz')) and path.relative_to(site).as_posix() not in keep:path.unlink()
    for path in root.glob('*'):
        if path.is_dir():
            with contextlib.suppress(OSError):path.rmdir()
    (site/'data/previous-manifest.json').unlink(missing_ok=True)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--months',type=int,default=60)
    ap.add_argument('--titles-months',type=int,default=2,help='Recent-title fallback window; 0 disables new title storage. Restored metadata is retained separately.')
    ap.add_argument('--no-paper-index',action='store_true',help='Publish counts only, without clickable paper indices.')
    ap.add_argument('--db',type=Path,default=ROOT/'.cache/physics-lite.sqlite')
    ap.add_argument('--legacy-db',type=Path,default=ROOT/'.cache/arxiv.sqlite')
    ap.add_argument('--site',type=Path,default=ROOT/'site')
    ap.add_argument('--local-only',action='store_true')
    ap.add_argument('--restore-metadata',action='store_true',help='With --local-only, reuse titles/authors/abstracts from the existing legacy DB; never download.')
    ap.add_argument('--max-pages',type=int,default=10000)
    ap.add_argument('--rebuild',action='store_true')
    ap.add_argument('--incremental-only',action='store_true',help='Fail before any request instead of starting a full-window download.')
    ap.add_argument('--vacuum',action='store_true',help='Reclaim free space in the new Lite database only.')
    a=ap.parse_args(argv)
    if not 2<=a.months<=120 or not 0<=a.titles_months<=12 or a.max_pages<1:ap.error('months=2..120, titles-months=0..12, max-pages>=1')
    if a.incremental_only and a.rebuild:ap.error('--incremental-only cannot be combined with --rebuild')
    if a.incremental_only and not a.db.is_file():ap.error('Completed Lite database is missing. No download was started.')
    if a.db.resolve()==a.legacy_db.resolve():ap.error('New and legacy databases must have different paths.')
    if a.restore_metadata and not a.local_only:ap.error('--restore-metadata requires --local-only; it must not start a download.')
    if a.restore_metadata and not a.db.is_file():ap.error('Lite database is missing; no database was created and no download was started.')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    as_of=datetime.now(UTC).replace(microsecond=0);tax=json.loads((ROOT/'scripts/taxonomy.json').read_text('utf-8'))
    contact=os.environ.get('ARXIV_CONTACT','').strip()
    client=SerialHTTP('PhysicsPulse/0.6.0 (metadata observatory'+('; mailto:'+contact if contact else '')+')')
    try:
        with collector_lock(a.db):
            db=connect_db(a.db)
            try:
                migrate_legacy(db,a.legacy_db,a.site,as_of,a.months,a.titles_months,a.local_only)
                months=a.months
                if a.local_only:as_of,months,coverage=local_coverage(db,a.months)
                else:
                    coverage=harvest(db,tax,as_of,months,client,a.titles_months,a.max_pages,a.rebuild,not a.no_paper_index,a.incremental_only);as_of=utc_datetime(coverage['to'])
                with db:
                    if not a.titles_months:db.execute('DELETE FROM recent_titles')
                    else:db.execute('DELETE FROM recent_titles WHERE id IN (SELECT id FROM papers WHERE created<?)',(epoch(shift_month(as_of,1-a.titles_months)),))
                if a.restore_metadata:paper_metadata.restore_legacy(db,a.legacy_db)
                rotation=prune_monthly(db,as_of,months,tax,full_window=coverage.get('fullWindow',False))
                data=aggregate(db,tax,as_of,months,coverage,a.titles_months,not a.no_paper_index);data['requestedMonths']=a.months
                data['retentionReport']=rotation
                publish(db,data,a.site)
                if a.vacuum or rotation['rotated']:db.execute('VACUUM')
                db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                LOG.info('Published %d months. Metadata coverage: %s. Missing fields remain unavailable.',months,data.get('metadataTotals',{}))
                LOG.info('New cache: %s (%.1f MiB). Next: python3 scripts/build.py',a.db,a.db.stat().st_size/1024**2)
                if a.legacy_db.exists():LOG.info('Legacy cache retained unchanged. Disk is not reclaimed until you separately remove/archive it: %s',a.legacy_db)
            finally:db.close()
    except KeyboardInterrupt:
        LOG.warning('Interrupted. Rerun the same command to resume committed pages.');return 130
    except (HarvestError,OSError,ValueError,sqlite3.Error) as exc:
        LOG.error('Update failed; no complete new result is claimed. %s',exc);return 1
    return 0


if __name__=='__main__':sys.exit(main())
