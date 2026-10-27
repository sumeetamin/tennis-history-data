# Grand Slam point-by-point supplement

This is an optional, post-match statistics supplement for the ATP/WTA main-tour
dataset. It covers the source archive's **available** Grand Slam singles logs;
it is not a complete match census. The upstream collection spans 2011–2024 and
is strongest for 2011–2017. It reports that it contains most main-draw singles
matches but misses matches, especially early rounds; Australian Open and French
Open files from 2018–2022 were transformed from another provider, and those
events were not collected from 2023 onward. See `UPSTREAM_README.md` and the
manifest for the exact files and pinned revision.

The source is [Jeff Sackmann's Grand Slam point-by-point archive](https://github.com/JeffSackmann/tennis_slam_pointbypoint),
retrieved through the [AngieXuAU mirror](https://github.com/AngieXuAU/tennis-point-by-point-archive).
Its license is **CC BY-NC-SA 4.0**. The source data dictionary is preserved in
`data_dictionary.txt`; please retain attribution and the non-commercial,
share-alike terms. This repo stores per-match aggregates, not the roughly
272 MB raw point-log files.

## Files

- `grand_slam_point_match_stats.csv.gz`: source-match level point, serve,
  return, first/second serve and event counts/rates.
- `archive_match_links.csv.gz`: event/round/player crosswalk to the repo's
  post-2000 archive, including unresolved rows and match-link evidence.
- `player_aliases.csv.gz`: source player IDs linked to canonical player IDs
  through unique match contexts. These are machine-generated; `human_reviewed`
  is `0` and they are not human-certified identities.
- `corrections.csv.gz`: append-only, last-write-wins corrections. Apply the
  latest correction by `(table_name, record_key)` to obtain the effective row.
- `manifest.json`: source revision, file hashes, counts and link status.

Blank statistics mean unavailable or unobserved; they must not be replaced
with zero. Event counts whose source columns are all zero are treated as
unavailable because zero may mean the field was not collected. Availability
flags distinguish missing from a measured zero. Rates are derived only when
their point denominator is observed.

The source has event/tournament and round context, but no verified match date,
start time, timezone, odds quote time or result-publication timestamp. The
archive crosswalk's event date is the tournament start date. Use the separate
experimental feature export only for a disclosed sensitivity experiment; its
28-day cutoff mitigates (but cannot prove away) chronology uncertainty. The
point-level metrics are post-match outcomes and must never be used as features
for the same match prediction.
