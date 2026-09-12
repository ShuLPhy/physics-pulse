#!/usr/bin/env python3
"""One replaceable, verified state snapshot in a dedicated GitHub Release.

Uses GitHub CLI authentication, never prints a token. Database assets have unique
names. A manifest is uploaded LAST. Old managed assets are deleted only after the
new pair is present. No SQLite binaries are committed to Git history.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import deploy_state as state
import update_data as m

TAG='pulse-data'
ASSET_RE=re.compile(r'^state-[0-9]{8}T[0-9]{6}-[a-f0-9]{8}\.(?:json|sqlite\.gz)$')


def gh(*args: str, input_text: str | None=None) -> str:
    p=subprocess.run(['gh',*args],input=input_text,text=True,capture_output=True)
    if p.returncode:
        raise m.HarvestError('GitHub operation failed: '+p.stderr.strip()[:1500])
    return p.stdout


def validate_repo(repo: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}',repo):
        raise m.HarvestError('Use owner/repository, not a URL.')
    return repo


def assets(repo: str) -> list[dict]:
    # A missing release is an error, never a reason to download five years again.
    return json.loads(gh('release','view',TAG,'--repo',validate_repo(repo),'--json','assets'))['assets']


def download(repo: str, directory: Path, target: Path) -> dict:
    entries=assets(repo)
    names={a['name'] for a in entries}
    manifests=sorted(n for n in names if state.STATE_RE.fullmatch(n)
                     and n.removesuffix('.json')+'.sqlite.gz' in names)
    if not manifests:raise m.HarvestError('No complete seed in the pulse-data release. Upload your local Lite seed; no harvest was started.')
    # Do not silently fall back from a corrupt latest committed snapshot.
    selected=manifests[-1]
    directory.mkdir(parents=True,exist_ok=True)
    gh('release','download',TAG,'--repo',repo,'--pattern',selected,'--dir',str(directory))
    manifest=directory/selected
    data=json.loads(manifest.read_text('utf-8'))
    expected=manifest.stem+'.sqlite.gz'
    if data.get('file')!=expected:raise m.HarvestError('Invalid manifest asset path.')
    gh('release','download',TAG,'--repo',repo,'--pattern',expected,'--dir',str(directory))
    return state.import_bundle(manifest,target)


def upload(repo: str, manifest: Path, *, prune: bool=True) -> None:
    validate_repo(repo)
    # Validate the local bundle before sending anything.
    with tempfile.TemporaryDirectory() as d:
        state.import_bundle(manifest,Path(d)/'check.sqlite')
    metadata=json.loads(manifest.read_text('utf-8'));blob=manifest.with_name(metadata['file'])
    prior=assets(repo)
    if any(a['name'] in (manifest.name,blob.name) for a in prior):
        raise m.HarvestError('State asset already exists; export a new bundle instead of overwriting it.')
    gh('release','upload',TAG,str(blob),'--repo',repo)
    # Commit marker is uploaded only after the DB upload returned success.
    gh('release','upload',TAG,str(manifest),'--repo',repo)
    uploaded={a['name']:a for a in assets(repo)}
    for p in (blob,manifest):
        entry=uploaded.get(p.name)
        if not entry or entry.get('size')!=p.stat().st_size:
            raise m.HarvestError('Remote asset verification failed; previous state was not deleted.')
    # Read back the committed pair before deleting the previous good state.
    with tempfile.TemporaryDirectory(prefix='pulse-verify-') as d:
        folder=Path(d)
        for p in (manifest,blob):
            gh('release','download',TAG,'--repo',repo,'--pattern',p.name,'--dir',str(folder))
        state.import_bundle(folder/manifest.name,folder/'check.sqlite')
    if prune:
        keep={blob.name,manifest.name}
        for a in uploaded.values():
            if ASSET_RE.fullmatch(a['name']) and a['name'] not in keep:
                gh('release','delete-asset',TAG,a['name'],'--repo',repo,'--yes')


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['download','upload'])
    ap.add_argument('--repo',required=True)
    ap.add_argument('--db',type=Path,default=m.ROOT/'.work/physics-lite.sqlite')
    ap.add_argument('--dir',type=Path,default=m.ROOT/'.work/incoming')
    ap.add_argument('--manifest',type=Path)
    a=ap.parse_args(argv)
    try:
        if a.action=='download':print(json.dumps(download(a.repo,a.dir,a.db)))
        else:
            if not a.manifest:ap.error('--manifest is required for upload')
            upload(a.repo,a.manifest)
    except (m.HarvestError,OSError,ValueError) as exc:ap.exit(1,str(exc)+'\n')

if __name__=='__main__':main()
