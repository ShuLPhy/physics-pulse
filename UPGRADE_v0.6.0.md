# Upgrade the already-published site to 0.6.0

This update is based on **0.5.0 hosting**, not the obsolete monthly branch.
Your existing site URL and daily schedule stay the same. Source is updated;
cloud state is not replaced by your Mac's older copy.

## 1. Apply in the original local `arxiv-pulse` folder

Stop a collector if one is running. Do NOT delete `.cache` or `.publish`.

```sh
unzip -o ~/Downloads/physics-pulse-v0.6.0-themes-update.zip
```

The ZIP contains no database, seed, public snapshot, credentials, or demo site.

## 2. Update the existing GitHub repo

The same `gh` browser login used for the initial publication is reused. The
repo is read from `.publish/*/launch.json`; it is not guessed from an account.

```sh
python3 scripts/upgrade_github.py
```

If the setup receipt is absent or identifies more than one repo, specify the
existing owner and repository (not the Pages URL):

```sh
python3 scripts/upgrade_github.py --repo YOUR_GITHUB_NAME/physics-pulse
```

Optional read-only preflight:

```sh
python3 scripts/upgrade_github.py --dry-run
```

The helper reads/clones the default branch, validates managed files against the
known 0.5.0 release, performs a normal commit/push and requests `refresh.yml`
with `mode=publish-only`. It NEVER force-pushes, creates a repository, uploads a
DB, replaces state-release assets, or dispatches an arXiv update. Concurrent
changes causing a non-fast-forward push fail rather than being overwritten.
A branch-protection or permission error also stops the helper.

The existing workflow, after obtaining its own latest verified state, classifies
saved metadata, validates the resulting site, persists updated cloud state and
publishes. Existing workflow concurrency continues to serialize this work with
the daily job. If state is missing or invalid, it stops, as in 0.5.0.

## 3. Confirm the Actions run

The helper prints the Actions URL but does not claim that deployment has
already completed. After a successful run, refresh the same public website and
select **Condensed Matter -> Themes**. Future daily runs classify the metadata
they already receive. No five-year backfill is scheduled.

Historical title/abstract coverage may be sparse. Blank history segments and
unavailable momentum then reflect input availability, not missing deployment.

## Custom edits / partial runs

The helper refuses to overwrite managed files whose hashes match neither the
known old release nor the new release. In that case, merge the changed source
files into your repo deliberately; do not disable the guard blindly. The helper
also rejects symlink/path traversal and altered local release files.

If a push succeeded but workflow dispatch failed, rerun the same command. It
recognizes matching new files and does not make duplicate commits. It does not
reset the public site or the rolling state release.

No authentication token needs to be pasted into a chat, script, or repository.

## Optional local preview

This is separate from GitHub deployment and does not update the public site:

```sh
python3 scripts/classify_themes.py && python3 scripts/build.py
```

No `update_data.py --months 60` is needed for this release.
