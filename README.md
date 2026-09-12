# Physics Pulse 0.6.0 - Research themes

New: an independent Condensed Matter theme explorer, separate title / abstract input cohorts, classification coverage, and safe in-place upgrades of the already-published site.

- Existing public site: see `UPGRADE_v0.6.0.md`. Do not repeat the initial publication/seed upload.
- Theme definitions, limitations and retention: see `THEMES.md`.
- Original hosting and daily update setup is retained below.

---

# Physics Pulse 0.5.0

Independent arXiv Physics observatory: five years of monthly treemaps, adaptive
line charts, author display and search over saved bibliographic fields.
Not affiliated with or endorsed by arXiv.

## Publish once; visit by URL

See **DEPLOY.md** for the exact GitHub Pages setup. The supported automated
production path is GitHub Pages + GitHub Actions. Netlify is NOT configured as
a second production target in this release.

The initial deployment reuses your completed `.cache/physics-lite.sqlite`.
No five-year download is started by any deployment helper. The daily workflow
refuses to run without a verified state snapshot.

```sh
# In your existing arxiv-pulse folder, after applying the v0.5.0 update:
brew install gh
gh auth login --hostname github.com --git-protocol https --web --scopes repo,workflow
python3 scripts/publish_github.py --name physics-pulse --public
```

These commands make a NEW PUBLIC repository under the GitHub account that you
log into, upload allowlisted source and a sanitized public-metadata seed, enable
Pages, and request the first deployment. They do not publish personal files,
`.env`, your legacy database, local import paths, or arbitrary SQLite tables.
Check the Actions result before treating the printed expected URL as live.

## Daily and monthly lifecycle

* Daily at 06:17 UTC / 15:17 Japan: fetch changes since the last successful
  harvest, with two days of overlap; update counts and observed title/authors.
  The schedule is best-effort, not a guaranteed exact execution time.
* Raw OAI XML and unused fields are never written to disk. Incoming abstracts
  continue to be discarded. Existing restored abstracts remain searchable
  until their paper's month expires. Missing historic authors/abstracts are
  not backfilled by separate requests.
* Keep exactly 60 calendar months of individual records, including the current
  month. At the first successful update after a UTC month changes, remove all
  older IDs, titles, authors and abstracts and their public index shards.
* Only category TOTALS for one preceding month are retained as a frozen
  comparison baseline. See RETENTION.md for its accuracy limitations.
* Build only a fully verified snapshot. A failed fetch/build does not replace
  the deployed website. DEMO data are rejected by the production validator.

## State and storage

Source lives in Git. The rolling state lives in the mutable `pulse-data`
GitHub Release, as a gzip SQLite asset and SHA-256 manifest. Do not enable
release immutability for this release. New state is uploaded and read back
before old managed assets are deleted. Only one successfully saved pair is
retained; interrupted uploads may leave temporary orphan assets until the
next successful save. Git history does NOT contain daily database snapshots.

The Pages build artifact is configured to expire after one day. The ephemeral
runner workspace is removed at the end of a run. Provider backups and CDN
caches are outside this program's control; this is not secure erasure.

Your Mac's original Lite database and legacy `arxiv.sqlite` are not automatically
deleted or kept in sync with the cloud. Keep the original seed until deployment
is confirmed. Stop local harvesters once daily cloud collection is enabled, to
avoid concurrent arXiv requests across machines.

## Existing local use

```sh
python3 scripts/update_data.py --local-only
python3 scripts/build.py
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

`--local-only` uses the verified saved snapshot time, not today's clock. It
never labels stale observations as freshly fetched. For a deliberate incremental
local update use `--incremental-only --months 60`; this blocks a full resync.

## Tests

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --check scripts/app.js
```

All tests use synthetic fixtures. See TEST_REPORT.md for what was actually
verified. A public URL, live GitHub run and your Mac's database are not
verified by these offline tests.

## Sources

API and hosting references verified 2026-09-12:

* https://info.arxiv.org/help/oa/index.html
* https://info.arxiv.org/help/api/tou.html
* https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
* https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
* https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
* https://cli.github.com/manual/gh_auth_login
* https://cli.github.com/manual/gh_release_upload

Code is MIT licensed. Public descriptive arXiv metadata is governed by the
provider's terms, not an exclusive claim by this project. No PDFs are hosted.
