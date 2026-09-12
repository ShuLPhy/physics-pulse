#!/usr/bin/env python3
"""Create a NEW public GitHub repo, upload a sanitized seed, enable Pages.

Requires `gh auth login` and an explicit --public. Never adopts or force-pushes
an existing user repository. A local receipt lets the same command resume its
own partially completed setup. No arXiv requests are made.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import deploy_state
import github_state
import prepare_publish
import update_data as m


def git(directory: Path,*args: str):
    result=subprocess.run(['git','-C',str(directory),*args],text=True,capture_output=True)
    if result.returncode:raise m.HarvestError('Git failed: '+result.stderr.strip()[:1200])
    return result.stdout


def start(name: str, db: Path, public: bool):
    if not public:raise m.HarvestError('--public is required. Code and sanitized public paper metadata will be publicly accessible.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}',name):raise m.HarvestError('Invalid repository name.')
    for binary in ('gh','git'):
        if not shutil.which(binary):raise m.HarvestError(f'{binary} is not installed. For GitHub CLI on Homebrew: brew install gh')
    user=json.loads(github_state.gh('api','user','--jq','{login:.login,id:.id}'))
    repo=github_state.validate_repo(user['login']+'/'+name)
    workspace=m.ROOT/'.publish'/name
    receipt=workspace/'launch.json'
    def save():m.atomic_write(receipt,json.dumps(progress,indent=2)+'\n')
    if receipt.is_file():
        progress=json.loads(receipt.read_text('utf-8'))
        if progress.get('repo')!=repo:raise m.HarvestError('The active GitHub account differs from the previous setup.')
    else:
        if workspace.exists() and any(workspace.iterdir()):raise m.HarvestError('A partial local preparation exists. Use a different --name or review .publish/'+name)
        report=prepare_publish.prepare(db,workspace)
        progress={'repo':repo,**report};save()
    source=Path(progress['source']);manifest=Path(progress['manifest'])
    if not progress.get('created'):
        github_state.gh('repo','create',repo,'--public','--description','Monthly physics research trends from arXiv metadata. Independent project.')
        progress['created']=True;save()
    if not progress.get('pushed'):
        if not (source/'.git').is_dir():
            git(source,'init','-b','main')
            git(source,'config','user.name',user['login'])
            git(source,'config','user.email',str(user['id'])+'+'+user['login']+'@users.noreply.github.com')
            git(source,'add','.')
            git(source,'commit','-m','Publish Physics Pulse v0.6.0 source')
            git(source,'remote','add','origin','https://github.com/'+repo+'.git')
        git(source,'-c','credential.helper=','-c','credential.helper=!gh auth git-credential','push','-u','origin','main')
        progress['pushed']=True;save()
    if not progress.get('release'):
        try:github_state.assets(repo)
        except m.HarvestError as exc:
            if '404' not in str(exc) and 'release not found' not in str(exc).lower():raise
            github_state.gh('release','create',github_state.TAG,'--repo',repo,'--target','main',
                           '--title','Physics Pulse rolling state','--prerelease','--latest=false',
                           '--notes','Public arXiv bibliographic metadata only. This mutable release keeps one current compressed state snapshot. Do not enable release immutability for this storage release.')
        progress['release']=True;save()
    if not progress.get('seed'):
        # Export a new uniquely named pair on retry, then remove prior managed pairs.
        if any(a['name'] in (manifest.name,manifest.stem+'.sqlite.gz') for a in github_state.assets(repo)):
            with tempfile.TemporaryDirectory() as d:
                temp=Path(d)/'verified.sqlite';deploy_state.import_bundle(manifest,temp)
                manifest=deploy_state.export_bundle(temp,workspace/'seed')
            progress['manifest']=str(manifest);save()
        github_state.upload(repo,manifest)
        progress['seed']=True;save()
    if not progress.get('pages'):
        endpoint=f'repos/{repo}/pages'
        try:result=json.loads(github_state.gh('api',endpoint))
        except m.HarvestError as exc:
            if '404' not in str(exc):raise
            result=json.loads(github_state.gh('api','--method','POST',endpoint,'-f','build_type=workflow'))
        if result.get('build_type')!='workflow':
            github_state.gh('api','--method','PUT',endpoint,'-f','build_type=workflow')
        progress['pages']=True;save()
    if not progress.get('dispatched'):
        github_state.gh('workflow','run','refresh.yml','--repo',repo,'--ref','main','-f','mode=publish-only')
        progress['dispatched']=True;save()
    print('Deployment requested (not yet confirmed complete).')
    print('Actions: https://github.com/'+repo+'/actions')
    print('Expected URL after successful deployment: https://'+user['login']+'.github.io/'+name+'/')
    print('The first run makes no arXiv requests. Daily updates run on GitHub, not this Mac.')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--name',default='physics-pulse');ap.add_argument('--public',action='store_true')
    ap.add_argument('--db',type=Path,default=m.ROOT/'.cache/physics-lite.sqlite')
    a=ap.parse_args()
    try:start(a.name,a.db,a.public)
    except (m.HarvestError,OSError,ValueError,KeyError) as exc:
        ap.exit(1,str(exc)+'\nNo full arXiv harvest was started. If setup created the repo, rerun the same command to resume.\n')

if __name__=='__main__':main()
