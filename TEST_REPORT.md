# Physics Pulse 0.6.0 - Verification report

This release extends the 0.5.0 hosting branch. Tests use synthetic records;
no private user database or production GitHub repository was accessed.

## Results

- **162 Python tests passed**: 118 existing regression tests plus 44 new tests.
- **129 browser checks passed**: 61 existing interface checks, 28 author/search
  checks, 31 theme interface checks, and 9 production-format transport checks.
- JavaScript syntax checks passed for the assembled application.

Python coverage includes separate title/abstract cohorts, unavailable vs
unmatched inputs, bounded phrases, accent normalization, parent union without
double counting, rule fingerprints, stale observations, changed titles, removed
abstracts, retained evidence after raw-text disposal, old state migration,
state round-tripping, monthly cascade deletion and orphaned shard cleanup.
It also covers a no-network publish-only cloud build with theme sidecars,
tampered count/hash rejection, and source-only upgrade safeguards.

A real **local Git bare-repository** integration test exercises preflight,
normal commit/push, an idempotent repeat and publish-only dispatch arguments.
The GitHub CLI API actions in that test are mocked. This is NOT a live GitHub
push or deployment test. No force push, seed upload, or arXiv backfill is used.

Browser checks cover Condensed Matter scope, 12/22-card display, facets, search,
cohort selection, count/prevalence charts, AUTO/nonzero and zero scales,
1Y/3Y/5Y, gap rendering, keyboard month selection, evidence, authors, list-only
intersections, unmatched papers, sparse-count gates, returning to the original
heatmap, and 390-pixel mobile overflow. Screenshots were visually inspected.

## Transport limitations

The browser environment blocks direct localhost navigation. Interface tests
therefore load HTML locally and replay fetch responses. The transport test
starts a real Python loopback HTTP server under a repository-style subpath,
requests the generated HTML and compressed shards using Python, and replays
those exact bytes through browser fetch. Gzip decoding, relative paths and
paper joins are exercised, but browser-to-server networking is NOT end-to-end
verified in this environment.

## Not verified

- Live arXiv/OAI requests, live GitHub API calls, or the user's deployed website.
- Real-paper classification precision/recall or expert agreement. The rules are
  a transparent lexical pilot, not validated scientific labels.
- Completeness of the user's five-year title/abstract history. Missing inputs
  remain visible; the upgrade does not redownload them.
- Stability of all browsers or custom changes made outside the supplied release.

## Reproduction (full source bundle)

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 scripts/make_theme_demo.py --output site/data/physics.json
python3 scripts/build.py
node --check scripts/theme_ui.js
python3 tests/browser_smoke.py
python3 tests/browser_metadata.py
python3 tests/browser_themes.py
python3 tests/browser_theme_http.py
```

The optional browser checks need Playwright and Chromium. Production collection
and classification use only the Python standard library and existing tools.
The standalone preview is completely synthetic and explicitly labeled DEMO.
