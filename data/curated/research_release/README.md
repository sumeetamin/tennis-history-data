# Current ATP/WTA research release

Use `main_draw_features.csv.gz` for the population with confirmed main-draw stages.
Use `main_tour_event_features.csv.gz` to include recent high-tier events with
unknown round/stage; filter `draw_status` explicitly. Neither file is a complete
official tournament census. Both start in 2000 and contain completed singles.

Historical rows use the existing archive export. Recent rows are freshly replayed
from current source results and the strict identity crosswalk, then joined to
available prior ranking and profile supplements. Unfinished or unverified recent
records remain in the original archive and appear in the current exclusion ledger.
The superseded append-only table under `../main_tour/` is retained for provenance.

These files are replaceable derived views: regenerating them repairs historical
derived values when backfilled source results change player history. Original raw
rows and append-only feature archives are preserved. `manifest.json` records source
hashes and file hashes. The [quality report](../../../docs/repository-quality.md)
reports observed missingness, source gaps and integrity checks.

## Timing and fields

- `p1_won` is the target. Player ordering is assigned independently of the winner.
- History uses only results older than the exclusive 28-day cutoff. Archive event
  dates approximate tournament start; this is not exact information-availability timing.
- `p1_rank_is_stale` / `p2_rank_is_stale` mark ranking snapshots older than 14 days;
  fallbacks are capped at 90 days. They are not actual match-day rankings.
- Unknown hands, heights, ranks, statistics and round names remain missing.
- Opening and last-pre-match Pinnacle odds are separate. Individual quote
  timestamps are unavailable in this provider; timing verification is false.
- Provider match datetimes are declared UTC, but actual start times are unverified.
- Current roster heights are not historical measurements. Model experiments and
  betting-return evaluations are outside this data release.

Rebuild in order after updating sources and building the local SQLite database:

```sh
python scripts/build_current_recent_snapshot.py
python scripts/build_recent_features_enriched.py
python scripts/build_research_release.py
python scripts/audit_repository_quality.py
```

Mixed-source license: CC BY-NC-SA 4.0 for Sackmann-derived data, plus Valuebetennis
CC BY 4.0 attribution and Wikidata CC0 facts. See `DATA_LICENSE.md` at the repo root.
