#!/usr/bin/env python3
"""Portable, sanitized state bundles. Does not contact arXiv or GitHub.

A SQLite online backup gives a consistent snapshot including committed WAL data.
We NEVER zip .cache/ or upload the user's original database. Only allowlisted
public metadata tables and required synchronization markers enter a new DB.
"""
from __future__ import annotations
import argparse
import contextlib
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import uuid
import update_data as m

MAX_DB_BYTES = 2 * 1024**3
STATE_RE = re.compile(r'^state-[0-9]{8}T[0-9]{6}-[a-f0-9]{8}\.json$')
TABLES = {
    'papers': ('id','created','category'),
    'recent_titles': ('id','title'),
    'paper_details': ('id','title','authors','abstract_gz','info_source'),
    'theme_classifications': ('id','rule_key','basis','input_hash','title_hash','hits','source'),
    'monthly_baseline': ('month','category','n'),
}
META_KEYS = ('coverage_from','snapshot_as_of','last_success','baseline_month',
             'individual_records_from','retention_months')


def digest(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def inspect_db(path: Path, months: int=60) -> dict:
    if not path.is_file():raise m.HarvestError('Completed Lite DB not found. No download was started: '+str(path))
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        columns=[r['name'] for r in db.execute('PRAGMA table_info(papers)')]
        if columns!=['id','created','category']:raise m.HarvestError('Not a Lite DB. Do not use arxiv.sqlite.')
        if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise m.HarvestError('SQLite integrity check failed.')
        if db.execute('PRAGMA foreign_key_check').fetchone():raise m.HarvestError('SQLite foreign-key check failed.')
        asof,covered,coverage=m.local_coverage(db,months)
        if covered!=months:raise m.HarvestError(f'Only {covered}/{months} months verified; no automatic download.')
        if not m.get_meta(db,'last_success'):raise m.HarvestError('last_success is missing.')
        now=datetime.now(timezone.utc)
        if (asof-now).total_seconds()>86400:raise m.HarvestError('Snapshot is dated in the future.')
        count=db.execute('SELECT COUNT(*) FROM papers').fetchone()[0]
        if not count:raise m.HarvestError('Empty database is not a production seed.')
        return {'asOf':m.stamp(asof),'coverageFrom':coverage['from'],'months':months,'papers':count}
    finally:db.close()


def sanitize_copy(source: Path, target: Path, months: int=60) -> dict:
    """Create a new DB with no free pages, private paths, arbitrary tables or logs."""
    info=inspect_db(source,months)
    if source.resolve()==target.resolve():raise m.HarvestError('Source and export paths must differ.')
    if target.exists():raise m.HarvestError('Export target already exists: '+str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    tax=json.loads((m.ROOT/'scripts/taxonomy.json').read_text('utf-8'))
    src=sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True);src.row_factory=sqlite3.Row
    dst=m.connect_db(target)
    try:
        src.execute('PRAGMA query_only=ON');src.execute('BEGIN')
        # Recheck synchronization state inside the snapshot used for the copy.
        asof,covered,_=m.local_coverage(src,months)
        if covered!=months:raise m.HarvestError('Coverage changed while exporting.')
        existing={r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        with dst:
            for table,columns in TABLES.items():
                if table not in existing:continue
                names=','.join(columns);marks=','.join('?' for _ in columns)
                cur=src.execute(f'SELECT {names} FROM {table}')
                while batch:=cur.fetchmany(1000):
                    dst.executemany(f'INSERT INTO {table} ({names}) VALUES ({marks})',[tuple(r) for r in batch])
            # Only necessary sync timestamps, no local legacy_import path.
            for key in META_KEYS:
                value=m.get_meta(src,key)
                if value is not None:m.put_meta(dst,key,value)
            # Bibliographic source is a controlled label, not a filename.
            dst.execute("UPDATE paper_details SET info_source=CASE WHEN info_source='oai' THEN 'oai' ELSE 'legacy-local' END")
        rotation=m.prune_monthly(dst,asof,months,tax)
        dst.execute('VACUUM');dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        # Portable single-file DB (no -wal/-shm required by the receiver).
        dst.execute('PRAGMA journal_mode=DELETE')
    finally:src.close();dst.close()
    info=inspect_db(target,months)
    info['rotation']=rotation
    return info


def export_bundle(source: Path, directory: Path, months: int=60) -> Path:
    directory.mkdir(parents=True,exist_ok=True)
    stem='state-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix='pulse-state-') as temporary:
        portable=Path(temporary)/'state.sqlite'
        info=sanitize_copy(source,portable,months)
        raw_size=portable.stat().st_size
        if raw_size>MAX_DB_BYTES:raise m.HarvestError('State exceeds the 2 GiB safety limit.')
        blob=directory/(stem+'.sqlite.gz')
        with portable.open('rb') as inp,blob.open('wb') as out:
            with gzip.GzipFile(filename='',fileobj=out,mode='wb',compresslevel=6,mtime=0) as gz:
                shutil.copyfileobj(inp,gz,1024*1024)
        manifest={'schemaVersion':1,'appVersion':'0.6.0','kind':'physics-pulse-state',
                  'createdAt':m.stamp(datetime.now(timezone.utc)),'file':blob.name,
                  'sha256':digest(blob),'compressedBytes':blob.stat().st_size,'sqliteBytes':raw_size,
                  **info,'publicMetadataOnly':True,'rawXMLIncluded':False}
        path=directory/(stem+'.json')
        m.atomic_write(path,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return path


def import_bundle(manifest_path: Path,target: Path) -> dict:
    if not STATE_RE.fullmatch(manifest_path.name):raise m.HarvestError('Unexpected state manifest filename.')
    data=json.loads(manifest_path.read_text('utf-8'))
    expected=manifest_path.stem+'.sqlite.gz'
    if data.get('kind')!='physics-pulse-state' or data.get('schemaVersion')!=1 or data.get('file')!=expected:
        raise m.HarvestError('Unrecognized state manifest.')
    size=data.get('sqliteBytes')
    if not isinstance(size,int) or not 0<size<=MAX_DB_BYTES:raise m.HarvestError('Invalid state size.')
    blob=manifest_path.with_name(expected)
    if not blob.is_file() or blob.stat().st_size!=data.get('compressedBytes') or digest(blob)!=data.get('sha256'):
        raise m.HarvestError('State file is missing or its checksum is incorrect. No full download will be attempted.')
    if target.exists():raise m.HarvestError('Refusing to overwrite an existing state DB: '+str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent,prefix='.state-',delete=False) as f:
        temporary=Path(f.name)
        try:
            n=0
            with gzip.open(blob,'rb') as inp:
                while block:=inp.read(1024*1024):
                    n+=len(block)
                    if n>size:raise m.HarvestError('Expanded database exceeds the declared size.')
                    f.write(block)
            if n!=size:raise m.HarvestError('Truncated database bundle.')
            f.flush();os.fsync(f.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True);raise
    try:
        info=inspect_db(temporary,data.get('months',60))
        if info['asOf']!=data['asOf']:raise m.HarvestError('State timestamps disagree.')
        os.replace(temporary,target)
        return info
    finally:temporary.unlink(missing_ok=True)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='action',required=True)
    e=sub.add_parser('export');e.add_argument('--db',type=Path,default=m.ROOT/'.cache/physics-lite.sqlite');e.add_argument('--output',type=Path,default=m.ROOT/'.seed')
    i=sub.add_parser('import');i.add_argument('manifest',type=Path);i.add_argument('--db',type=Path,required=True)
    a=ap.parse_args(argv)
    try:
        if a.action=='export':print(export_bundle(a.db,a.output))
        else:print(json.dumps(import_bundle(a.manifest,a.db)))
    except (m.HarvestError,OSError,ValueError,sqlite3.Error) as exc:
        ap.exit(1,'State error: '+str(exc)+'\n')

if __name__=='__main__':main()
