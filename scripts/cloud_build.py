#!/usr/bin/env python3
"""Build only from an imported verified DB; never create a new full harvest.

A failed run exits before Pages upload. The previously published site remains.
Working files are disposable; durable state is uploaded separately after checks.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import deploy_state
import update_data as m
import validate_site


def build(db: Path,site: Path,output: Path,*,update: bool=False) -> Path:
    deploy_state.inspect_db(db,60)
    # A fresh output tree is required, so stale generation data cannot leak.
    if site.exists() and any(site.iterdir()):raise m.HarvestError('Choose an empty staging site directory.')
    args=['--db',str(db),'--legacy-db',str(db.parent/'DO-NOT-IMPORT-LEGACY.sqlite'),
          '--site',str(site),'--months','60','--titles-months','2','--vacuum']
    args+=['--incremental-only','--max-pages','500'] if update else ['--local-only']
    code=m.main(args)
    if code:raise m.HarvestError('Collection did not complete. Existing public deployment is unchanged.')
    subprocess.run([sys.executable,str(m.ROOT/'scripts/build.py'),'--output',str(site/'index.html'),
                    '--embed',str(site/'data/physics.json')],check=True)
    report=validate_site.validate(site,allow_stale=not update)
    # No absolute file paths, private contact, tokens, or input payload in health.
    m.atomic_write(site/'health.json',json.dumps(report,indent=2)+'\n')
    m.atomic_write(site/'.nojekyll','')
    validate_site.validate(site,allow_stale=not update)
    return deploy_state.export_bundle(db,output,60)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db',type=Path,default=m.ROOT/'.work/physics-lite.sqlite')
    ap.add_argument('--site',type=Path,default=m.ROOT/'.work/site')
    ap.add_argument('--output',type=Path,default=m.ROOT/'.work/outgoing')
    ap.add_argument('--update',action='store_true')
    a=ap.parse_args()
    try:
        manifest=build(a.db,a.site,a.output,update=a.update)
        import os
        if output:=os.environ.get('GITHUB_OUTPUT'):
            with open(output,'a') as f:f.write('manifest='+str(manifest)+'\n')
        print('Ready for deployment. State manifest:',manifest)
    except (m.HarvestError,OSError,ValueError,subprocess.CalledProcessError) as exc:ap.exit(1,str(exc)+'\n')

if __name__=='__main__':main()
