# Deploy Physics Pulse v0.5.0 to GitHub Pages

## 1. Keep your existing completed data

Apply the update ZIP in your existing `arxiv-pulse` directory. Do not delete
`.cache/physics-lite.sqlite`. Do not switch back to the old `monthly` release.
No `update_data.py --months 60` run is needed for deployment.

Stop any local metadata collector. The local HTTP server can remain running
while preparing deployment; it is unnecessary once Pages works.

## 2. Log into GitHub on the Mac

A GitHub account and GitHub CLI (`gh`) are required. On a Homebrew-equipped Mac:

```sh
brew install gh
gh auth login --hostname github.com --git-protocol https --web --scopes repo,workflow
```

Skip installation if `gh --version` works. Authorize GitHub in the browser.
Never paste your password or token into ChatGPT or put it in the source code.
The daily workflow uses GitHub's built-in short-lived token. No S2_API_KEY,
Netlify token, paid ranking API, or separately stored PAT is required.

## 3. Create the public site

From the existing project directory:

```sh
python3 scripts/publish_github.py --name physics-pulse --public
```

The script uses the currently logged-in GitHub user's account. `--public`
explicitly means both source code and the public bibliographic state bundle
will be publicly accessible. A new repository named `physics-pulse` is created.
It will NOT overwrite/adopt a repository that already exists. Choose another
`--name`, e.g. `physics-pulse-observatory`, in that case.

The helper:

1. Checks that your Lite DB contains a verified completed 60-month window.
   A file size or minimum date alone is NOT considered proof of completion.
2. Creates an allowlisted source copy under `.publish/NAME/source` and a new
   sanitized portable DB in `.publish/NAME/seed`; the original is read-only.
3. Creates a public GitHub repository, pushes source (not DBs), uploads the
   seed to the `pulse-data` release, and sets Pages to GitHub Actions.
4. Requests `Publish Physics Pulse daily` in `publish-only` mode, which uses
   the seed WITHOUT requesting arXiv metadata.

A local setup receipt allows the same command to resume its own partial
setup. It does not contain a password/token. If the remote repository was
created but the process stopped before recording that fact, do not force-push
or delete it blindly; use a different new name or review the repository first.

The script prints an Actions URL and an EXPECTED Pages URL. Check the workflow
turns green before treating it as deployed. Open repository Settings > Pages
for the actual published URL. Repository or organization policies may require
you to approve the `github-pages` environment, enable Actions, or select
Settings > Pages > Build and deployment > Source > GitHub Actions yourself.
Then rerun the same command. This does not restart a five-year harvest.

## Daily operation

`refresh.yml` schedules every day at 06:17 UTC (15:17 Japan). A scheduled run
always does a guarded incremental update. GitHub may delay/drop runs; arXiv
publication/indexing also has a delay. The website exposes the actual snapshot
`asOf` and `health.json`, never the time the visitor happened to open it.

For a manual run choose Actions > Publish Physics Pulse daily > Run workflow:

* `publish-only`: rebuild using saved metadata, no arXiv calls.
* `update`: fetch changes, then prune/build/publish.

Optional: set repository Secret `ARXIV_CONTACT` to a contact email for the
collector's User-Agent. It is not copied into the public site or state export.
Do not run your Mac collector at the same time as the cloud collector. The
arXiv rate limit applies across your machines, not separately per machine.

Every successful publication updates `.github/publication.json` with a small
publication status. This records genuine repository activity; no article
history is committed. If updates fail for a prolonged period, inspect Actions.
GitHub can disable schedules after 60 days without repository activity. Enable
workflow failure notifications in your GitHub settings; no external alerting
service is configured by this package.

## Failure and storage behavior

The workflow is serialized and cancels no running update. A missing, incomplete,
corrupt or too-short state snapshot fails WITHOUT a full-window harvest. API
errors or invalid generated data fail before the Pages deployment step, so the
existing public website remains. If state saving succeeds but Pages fails, the
next run can still rebuild from the newer verified state.

The `pulse-data` release must stay mutable. Release immutability policies or
restricted repository permissions can block replacement; the tool stops with
an error rather than deleting unverified old state. Old managed state assets
are deleted only after a read-back verification of the new pair. Do not store
unrelated data under names starting `state-` in that dedicated release.

The published site has a conservative 900 MiB size guard. Retaining a rolling
60 months bounds the time span, not an absolute number of bytes: future growth
in submissions can still increase storage size.

## Manual browser-only setup (no GitHub CLI)

Prepare locally without network:

```sh
python3 scripts/prepare_publish.py
```

This creates `.publish/package/source` and `.publish/package/seed`. Create a
new public repository and upload ONLY the source directory's contents,
including `.github/workflows/refresh.yml` and `.github/publication.json`.
On macOS, Command+Shift+. reveals hidden files in Finder. Do not upload your
whole working folder. If browser upload cannot preserve the hidden directory,
create `.github/workflows/refresh.yml` explicitly using Add file > Create new
file, using the supplied file's contents.

Create a release tagged `pulse-data`, mark it a pre-release, and attach BOTH
files in the seed directory (`state-....sqlite.gz` and `state-....json`). Do not
enable immutability. Select Pages > Source > GitHub Actions, then manually run
`publish-only`. The same daily workflow subsequently applies.

## Netlify

This release intentionally uses one supported production target: GitHub Pages.
Uploading `site/` to Netlify alone does NOT connect the daily collection job.
No Netlify deployment or tokens are configured here.

## Limits of this handoff

The source code and offline tests are supplied. The user still needs to
connect/authenticate GitHub, upload their local seed and run the deployment.
No live URL or active scheduled job is claimed until GitHub confirms success.
