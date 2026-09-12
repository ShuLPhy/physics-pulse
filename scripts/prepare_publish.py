#!/usr/bin/env python3
"""Create an allowlisted source package and sanitized seed, without network.

Does not modify the source Lite DB. Does not copy .cache, site, .env, logs,
legacy DB, absolute local import paths, Git history or unrecognized files.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import deploy_state
import update_data as m

# Explicit file allowlist, not arbitrary scripts/* or the user's entire folder.
SCRIPT_NAMES=('app.js','build.py','index.template.html','oai.py','paper_metadata.py',
 'restore_metadata.py','style.css','taxonomy.json','update_data.py','deploy_state.py',
 'github_state.py','validate_site.py','cloud_build.py','record_publication.py',
 'prepare_publish.py','publish_github.py')
ROOT_FILES=('README.md','DEPLOY.md','RETENTION.md','TEST_REPORT.md','LICENSE','VERSION','.gitignore')
TEST_NAMES=('test_pipeline.py','test_metadata.py','test_deployment.py')


def prepare(db: Path, output: Path) -> dict:
    if output.exists() and any(output.iterdir()):raise m.HarvestError('Output directory is not empty; choose a new --output.')
    # Validate BEFORE writing anything or creating a remote repository.
    deploy_state.inspect_db(db)
    output.mkdir(parents=True,exist_ok=True)
    source=output/'source';source.mkdir()
    selected=list(ROOT_FILES)+['scripts/'+n for n in SCRIPT_NAMES]+['tests/'+n for n in TEST_NAMES]+['.github/workflows/refresh.yml']
    for rel in selected:
        src=m.ROOT/rel
        if src.is_symlink() or not src.is_file():raise m.HarvestError('Expected source file is missing or is a symlink: '+rel)
        dest=source/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    m.atomic_write(source/'.github/publication.json',json.dumps({'appVersion':'0.5.0','status':'not-yet-deployed'},indent=2)+'\n')
    manifest=deploy_state.export_bundle(db,output/'seed')
    report={'source':str(source.resolve()),'manifest':str(manifest.resolve())}
    m.atomic_write(output/'package.json',json.dumps(report,indent=2)+'\n')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db',type=Path,default=m.ROOT/'.cache/physics-lite.sqlite')
    ap.add_argument('--output',type=Path,default=m.ROOT/'.publish/package')
    a=ap.parse_args()
    try:print(json.dumps(prepare(a.db,a.output),indent=2))
    except (m.HarvestError,OSError,ValueError) as exc:ap.exit(1,str(exc)+'\n')

if __name__=='__main__':main()
