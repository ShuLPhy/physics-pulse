#!/usr/bin/env python3
"""Reclassify only available local metadata; never contact arXiv.

The same backfill runs automatically inside cloud_build.py on imported cloud
state. This command is only for an optional local preview, not cloud seeding.
"""
from pathlib import Path
import argparse
import update_data as m

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=m.ROOT/'.cache/physics-lite.sqlite')
    p.add_argument('--site',type=Path,default=m.ROOT/'site')
    a=p.parse_args()
    if not a.db.is_file():p.exit(1,'Completed Lite DB is missing. Nothing created; no download.\n')
    return m.main(['--db',str(a.db),'--site',str(a.site),'--local-only','--months','60',
                   '--legacy-db',str(a.db.parent/'DO-NOT-IMPORT-LEGACY.sqlite')])
if __name__=='__main__':raise SystemExit(main())
