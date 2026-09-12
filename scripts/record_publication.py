#!/usr/bin/env python3
"""Record a successful deployment; only a tiny status file enters git history."""
import argparse
import base64
import json
from pathlib import Path
from datetime import datetime, timezone
from github_state import gh, validate_repo


def record(repo,health):
    validate_repo(repo)
    info=json.loads(Path(health).read_text('utf-8'))
    endpoint=f'repos/{repo}/contents/.github/publication.json'
    previous=json.loads(gh('api',endpoint))
    content=json.dumps({'appVersion':'0.5.0','dataAsOf':info['asOf'],
                        'visibleMonths':info['visibleMonths'],
                        'publishedAt':datetime.now(timezone.utc).isoformat(timespec='seconds')},indent=2)+'\n'
    request={'message':'Record successful Physics Pulse publication [skip ci]',
             'sha':previous['sha'],'content':base64.b64encode(content.encode()).decode()}
    gh('api','--method','PUT',endpoint,'--input','-',input_text=json.dumps(request))

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--repo',required=True);ap.add_argument('--health',type=Path,required=True)
    a=ap.parse_args();record(a.repo,a.health)
