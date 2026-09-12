#!/usr/bin/env python3
"""Upgrade an existing Physics Pulse repo; do not upload/replace its live DB.

Finds the repo from this project's original .publish/*/launch.json receipt or
an explicit --repo OWNER/NAME. Fresh clone, managed-file hash checks, a normal
fast-forward push (never force), then dispatch publish-only. --dry-run performs
read-only GitHub calls and builds a diff but never pushes or dispatches.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import github_state
import update_data as m


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def resolve_repo(explicit=None):
    if explicit:return github_state.validate_repo(explicit)
    found=set()
    for p in (m.ROOT/'.publish').glob('*/launch.json'):
        try:
            v=json.loads(p.read_text('utf-8'))
            if v.get('created') and v.get('repo'):found.add(github_state.validate_repo(v['repo']))
        except (ValueError,OSError):continue
    if len(found)!=1:raise m.HarvestError('Cannot identify one existing repository. Use --repo OWNER/NAME. No repository is created.')
    return found.pop()

def plan(source,remote,manifest):
    changes=[]
    for rel,item in manifest['files'].items():
        p=Path(rel)
        if p.is_absolute() or '..' in p.parts or not (rel.startswith(('scripts/','tests/')) or rel in ('VERSION','README.md','THEMES.md','UPGRADE_v0.6.0.md','TEST_REPORT.md')):
            raise m.HarvestError('Invalid managed release path: '+rel)
        local=source/rel;target=remote/rel
        if local.is_symlink() or not local.is_file() or sha(local)!=item['new']:
            raise m.HarvestError('Local update file differs from the verified release: '+rel)
        if not target.resolve().is_relative_to(remote.resolve()):raise m.HarvestError('Repository path escapes its root: '+rel)
        if target.is_symlink():raise m.HarvestError('Refusing a symlink in repository: '+rel)
        if target.exists():
            value=sha(target)
            if value==item['new']:continue
            if value not in item.get('old',[]):
                raise m.HarvestError('Repository has custom changes; automatic overwrite stopped: '+rel)
        elif item.get('old'):
            raise m.HarvestError('Expected managed source file is missing: '+rel)
        changes.append(rel)
    return changes

def run(repo,dry_run=False):
    for name in ('gh','git'):
        if not shutil.which(name):raise m.HarvestError('Required executable not found: '+name)
    manifest=json.loads((m.ROOT/'scripts/release_manifest.json').read_text('utf-8'))
    info=json.loads(github_state.gh('repo','view',repo,'--json','nameWithOwner,defaultBranchRef'))
    if info['nameWithOwner'].lower()!=repo.lower():raise m.HarvestError('Repository name mismatch')
    branch=info['defaultBranchRef']['name']
    with tempfile.TemporaryDirectory(prefix='physics-pulse-upgrade-') as tmp:
        clone=Path(tmp)/'repo'
        github_state.gh('repo','clone',repo,str(clone),'--','--depth','1','--branch',branch)
        changes=plan(m.ROOT,clone,manifest)
        for rel in changes:
            p=clone/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(m.ROOT/rel,p)
        # The manifest is public source metadata, not the DB/state manifest.
        target=clone/'scripts/release_manifest.json'
        if target.is_symlink() or not target.resolve().is_relative_to(clone.resolve()):raise m.HarvestError('Unsafe manifest path in repo')
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists() or sha(target)!=sha(m.ROOT/'scripts/release_manifest.json'):
            shutil.copyfile(m.ROOT/'scripts/release_manifest.json',target);changes.append('scripts/release_manifest.json')
        print('Repository:',repo,'Branch:',branch)
        print('Managed files:',len(changes),'No DB/state asset will be uploaded.')
        if dry_run:
            print('\n'.join(changes));print('DRY RUN: no push, no workflow dispatch.');return
        def git(*args):
            proc=subprocess.run(['git','-C',str(clone),*args],capture_output=True,text=True)
            if proc.returncode:raise m.HarvestError('Git failed (never force-push): '+proc.stderr[-1500:])
            return proc.stdout
        if changes:
            user=json.loads(github_state.gh('api','user','--jq','{login:.login,id:.id}'))
            git('config','user.name',user['login']);git('config','user.email',str(user['id'])+'+'+user['login']+'@users.noreply.github.com')
            git('add','--',*changes);git('commit','-m','Add Physics Pulse v0.6.0 research themes')
            git('-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','origin','HEAD:'+branch)
        # Check hash/current branch before dispatch: never request --update here.
        github_state.gh('workflow','run','refresh.yml','--repo',repo,'--ref',branch,'-f','mode=publish-only')
        print('Requested publish-only; GitHub will classify its existing cloud DB locally.')
        print('Deployment is not yet confirmed. Check https://github.com/'+repo+'/actions')
        print('After success, future scheduled runs classify already-received daily changes.')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo');ap.add_argument('--dry-run',action='store_true');a=ap.parse_args()
    try:run(resolve_repo(a.repo),a.dry_run)
    except (m.HarvestError,OSError,ValueError,KeyError) as e:ap.exit(1,str(e)+'\nStopped. No forced overwrite and no arXiv backfill.\n')
if __name__=='__main__':main()
