# Storage and deletion policy (v0.5.0)

All calendar boundaries below are UTC, matching existing counts. The schedule
is 06:17 UTC / 15:17 Japan. Rotation occurs on the first SUCCESSFUL update after
a month boundary, not at a promised midnight wall-clock instant.

| Data | Policy |
| --- | --- |
| HTTP response XML | Kept in memory for one page, parsed, then discarded. No raw XML cache or raw-payload logs. |
| Paper ID, v1 timestamp, primary category | Retained for the current month plus 59 preceding calendar months. |
| Titles/authors | Retain already saved/observed metadata for those same papers; missing old fields stay missing. |
| Incoming abstract | Discarded, as in v0.4.1. No historical abstract refetch. |
| Previously restored abstract | Kept gzip-compressed for the paper's remaining retention period; searchable if saved. |
| Comparison baseline | Only one preceding month's aggregate counts by category. No IDs, titles, authors or abstracts. |
| Public paper index shards | Rebuilt by month/area. Unreferenced old shards are removed, never exposed in the new deployment. |
| Cloud state snapshots | One current verified manifest/database pair in a dedicated mutable release. No history of DB binaries in Git. |
| Temporary runner data | Deleted at end of job. GitHub Pages transfer artifact expires after one day. |
| Mac input DBs | Untouched by export/deploy helpers. Local originals/backups are NOT managed by cloud rotation. |

Example: September 2026 shows October 2021--September 2026. In October 2026,
October 2021's individual records are deleted and November 2021--October 2026
becomes visible. Only October 2021's per-category totals remain as the oldest
visible month's comparison baseline. September 2021's baseline totals are
replaced, not accumulated. The DB uses foreign-key cascades to remove attached
metadata, then VACUUM/portable export reclaims unused database pages.

## Accuracy boundaries

Once a baseline month has been compacted to totals, later category changes or
deletions for that already discarded month's individual papers cannot be
reconciled without retaining their IDs. Therefore its baseline is a frozen
aggregate, not a permanently exact contemporary recount. Visible months still
receive ordinary OAI changes. Data are grouped by v1 submission timestamp and
current primary category, not announcement date or historical category.

The update fetch overlaps two days using metadata modification dates, then
counts by v1 timestamp. Revised papers are not counted as new submissions.
The collector never fabricates zero observations when collection fails.

## Deletion is not secure erasure

The application removes expired data from its active database, current public
files and managed release assets. It cannot erase somebody else's downloads,
GitHub's internal backups, historical deployment/CDN caches, or your Mac's local
backup copies. A failed save/deployment can leave temporary older copies until
the next successful cleanup. Do not claim legal/forensic secure deletion.

## Why not discard all metadata every day?

The five-year chart and clickable historic lists require retained observations.
Daily disposal therefore means raw responses, unused fields and temporary files;
it does not mean deleting all paper IDs and then downloading five years again.
