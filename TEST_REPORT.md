# Physics Pulse 0.5.0 verification

Tested in this build session on 2026-09-12 using Python 3.13 and Chromium.

## Passed

* 118 Python unittest cases: 69 existing parser/storage/metadata cases plus
  49 deployment/rotation/state/bootstrap cases. One prior assertion was
  narrowed from all meta keys to existing synchronization markers because
  retention now intentionally adds its own explicit markers.
* 61 existing browser regression checks: treemap, monthly line chart, automatic
  nonzero vertical scale, keyboard/mobile interaction, watchlist and counts.
* 28 existing metadata browser checks: author display, saved abstract matching,
  query fields, missing-data messages, malicious-markup escaping and gzip.
* JavaScript syntax check (`node --check scripts/app.js`) and Python compilation.
* Workflow YAML parsing and static assertions for daily cron, serialized runs,
  GitHub Pages environment, one-day artifact retention, no action cache dependency.

New Python coverage includes: 60-month individual-record rotation; cascading
removal of author/abstract details; single frozen baseline total; repeated same-
month pruning; multi-month jumps; no automatic full harvest; read-only seed
export; private metadata/table exclusion; gzip/size/SHA validation; corrupt and
incomplete seed rejection; unique release assets; upload ordering; read-back
verification; previous state preservation on upload failure; synthetic first
publication with no arXiv calls; CLI setup resume without recreating/seeding the
repository twice; and refusing to adopt an existing remote repository.

## Limits

Fixtures are synthetic. No five-year real-data harvest, authenticated GitHub
API request, repository creation, real scheduled run or Pages deployment was
performed here. The user must authenticate and supply their actual local DB.
GitHub responses in unit tests are mocks; they do not prove live authorization
or service availability.

The 89 browser checks use injected pages and mocked fetch with real compressed
fixture payloads. The metadata suite also verifies Python localhost HTTP file
serving. A separate attempt to navigate Chromium to an actual localhost project
URL was blocked by this environment (`ERR_BLOCKED_BY_ADMINISTRATOR`); that
end-to-end browser-navigation scenario is NOT counted as passed. No attempt
was made to bypass that restriction.

The application still needs first-live-deployment verification in GitHub Actions,
including Pages permissions, API response behavior, and the user's data volume.
No active public URL or running daily job is claimed by this test report.
