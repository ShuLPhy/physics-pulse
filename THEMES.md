# Physics Pulse 0.6.0 - Research themes

## What this release does

The official research-area heatmap, authors, stored-abstract search, stock-like
line charts and existing daily deployment remain intact. A separate **Themes**
view is available for primary-category **Condensed Matter** papers only.

This is an independent, English-phrase-based pilot, not author-assigned subject
labels, an APS-approved classifier, a semantic model, or a complete physics
ontology. It contains 22 labels across phenomena, physical systems and methods.
The initial view shows twelve; facets, search and Show all expose the rest.

Reference material: APS's faceted organization and the linked concept records
listed in `scripts/themes.json`. Only three labels have direct concept-reference
links; other labels and all matching aliases are locally curated. Broader rules
such as the Quantum Hall / fractional Chern grouping are not claimed to be
identical to the linked official concept. Concept data are CC0; logos and the
name are not appropriated as the site's brand.

- https://physh.org/about
- https://physh.org/licensing
- https://physh.org/concepts/295dd02d-5447-477d-8f0b-0760bd7f1e39
- https://physh.org/concepts/9017d068-f9d7-42f8-b083-a385e9b14c0b
- https://physh.org/concepts/70623632-e9d5-4eaa-b6b3-95c6b0ce0b9c

## Input cohorts: do not manufacture a historical trend

The default cohort is **title only**, even when an abstract happens to be saved.
The optional **title + abstract** cohort requires BOTH inputs. It is never filled
with title-only classifications. A paper with no title is unavailable, not a
negative match. A paper with a title but no matching dictionary phrase is shown
under **No dictionary match**. This bucket supports manual review; it is not an
automatically named new topic.

For each month, each cohort keeps the number of eligible records, unmatched
records and distinct hits per label. Prevalence is `hits / eligible inputs`, NOT
`hits / all papers` and not an extrapolation for unavailable metadata. The
eligible-input fraction of all Condensed Matter papers is displayed separately.
A hit is an observed phrase mention, not proof that the theme is the main focus.
Overlap is intentional: percentages across labels need not sum to 100%.
Localization is a union of its own rules and its children, not their sum.

Trend ranking compares the last three completed months at/before the selected
month against the preceding three. Rates use pooled eligible counts, not a
simple mean of monthly percentages. The partial current month is excluded.
Initial display guards:

- Every month of the six-month comparison has at least 90% input eligibility.
- Pooled input eligibility differs by at most 5 percentage points.
- Each period has at least 30 hits for a numerical momentum value.

Otherwise a reason is shown instead of a volatile ranking number. Zero old hits
and at least five new hits can be marked an emerging *candidate*, never an
infinite growth rate. These gates are practical display rules, not confidence
intervals, hypothesis tests, multiple-testing correction, or seasonality control.

The chart retains the full calendar x-axis. Months below 90% eligibility are
**gaps**, not zeros and not joined by a line. Their detected counts can still be
inspected by selecting the month. AUTO fits the observed range; LOW/HIGH and
actual axis values remain visible. A zero origin is optional. The current
partial month is opt-in and dashed. Chart range is 1Y/3Y/5Y; plotted quantities
can be detected counts or prevalence. Prevalence is among eligible inputs.
Small sparklines show the latest 36 **completed** months and also preserve gaps.

A theme's paper list spans the official Condensed Matter categories. Titles,
authors and saved abstracts are joined from existing compressed category files;
there is no duplicate full-text theme store. Another tag can intersect the list.
That intersection and free-text search filter **the list only**, not the chart
or headline counts; the UI marks this explicitly. Search scope remains the
selected month, and unavailable abstracts are not searchable.

## Classification and retention

`scripts/themes.json` freezes version `cm-1.0.0`, aliases, grouping and gates.
`ruleKey` includes a configuration SHA-256 prefix. The matching engine version
is named there too; change it when changing normalization/matching semantics.
Do not change semantics under the same engine/version label.

Matching is case-insensitive, normalizes Unicode accents and separators, and
uses word boundaries. A generic `ML`, `DFT`, `QHE`, or `neural network` does not
alone imply a method tag. Ambiguous mentions, negation, contextual relevance,
non-English phrases and technical synonyms can still produce false positives
or missed papers. Review examples and unmatched papers before interpreting the
rankings scientifically. The release does not claim a measured accuracy on
real arXiv labels.

On first deployment, classification reads existing titles/restored abstracts
locally. No historical arXiv download is launched. On later daily updates, the
already-received OAI abstract is used in memory before it is discarded. Only
label IDs, dictionary evidence phrases, input hashes, source type, cohort and
rule key are stored in `theme_classifications`. **New raw abstracts are not
saved.** Previously restored compressed abstracts remain subject to the old
retention policy and can still be searched.

If a record is updated, observed tags replace old tags; a changed title
invalidates its old abstract-derived tags. The latest observed classification
is not overwritten by an older restored abstract. A rules change discards old
rule-key rows; saved inputs can be reclassified, but discarded inputs cannot.
Their coverage falls rather than silently mixing incompatible rule versions.
Past-month classification uses the metadata observed at collection time, not
necessarily the wording/classification on the original submission date.

Expired papers cascade-delete their classifications at the existing monthly
60-month rollover. The one older baseline remains only official-category
counts; no older individual theme records are retained. The daily cloud state
export explicitly includes the new table, so tags are not lost between runners.
Published month sidecars are hashed, count-checked and removed when obsolete.

## Deployment

Use `scripts/upgrade_github.py` as described in `UPGRADE_v0.6.0.md`. It updates
source only. The first workflow uses **publish-only** and reuses the existing
cloud state. Do not rerun the first-time `publish_github.py` or upload an old
local seed over a newer cloud DB. The original daily workflow is not replaced.

For an optional local preview with an already-completed Lite DB:

```sh
python3 scripts/classify_themes.py && python3 scripts/build.py
```

From the full source bundle, for synthetic browser fixtures only (development
fixtures are not in the update ZIP; never use them as production state):

```sh
python3 scripts/make_theme_demo.py --output demo/physics-themes.json
python3 scripts/build.py --embed demo/physics-themes.json --output demo/index.html
```

No API key, language model, machine-learning library, embedding service, or
additional third-party browser request is required.
