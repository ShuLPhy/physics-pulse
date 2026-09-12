#!/usr/bin/env python3
"""Restore bibliographic fields from local legacy data, without any requests.

Never calls the OAI harvester; no requests are made, including if the source is
missing. A valid completed Lite cache is required. Existing sync markers and
counts are preserved. --legacy-db accepts an archived legacy database path.
"""
from pathlib import Path
import argparse
import json
import sys
import update_data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, default=update_data.ROOT/'.cache/physics-lite.sqlite')
    ap.add_argument('--legacy-db', type=Path, default=update_data.ROOT/'.cache/arxiv.sqlite')
    ap.add_argument('--site', type=Path, default=update_data.ROOT/'site')
    a = ap.parse_args()
    if not a.db.is_file():
        ap.error('physics-lite.sqlite was not found. Run from your existing project; no download has been started.')
    try:
        snapshot = json.loads((a.site/'data/physics.json').read_text('utf-8'))
    except (OSError, ValueError) as exc:
        ap.error('A previously built LIVE monthly snapshot is required: '+str(exc))
    if snapshot.get('schemaVersion') != 3 or snapshot.get('mode') != 'live':
        ap.error('The current site is not a LIVE Lite snapshot. No data were modified.')
    months = snapshot.get('requestedMonths') or len(snapshot.get('monthStarts',[]))
    titles = snapshot.get('titleMonths',2)
    args = ['--local-only','--restore-metadata','--months',str(months),'--titles-months',str(titles),
            '--db',str(a.db),'--legacy-db',str(a.legacy_db),'--site',str(a.site)]
    if not snapshot.get('paperIndexEnabled',True):
        args.append('--no-paper-index')
    return update_data.main(args)


if __name__ == '__main__':
    sys.exit(main())
