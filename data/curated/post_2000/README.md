# Post-2000 results release

Start with `matches/`: one compressed CSV per tour and year, with the same schema.
Join `winner_id` and `loser_id` to `players.csv.gz`. See `manifest.json` for exact
counts, source dates, hashes and exclusions; `coverage.csv` breaks down field
availability by year, tour, source category and source. `validation_report.json`
records the full export checks.

This is a results dataset, **not a pre-match feature matrix**. Winner/loser ordering,
scores, current-match statistics and duration reveal the outcome. They must not
be passed directly to a predictive model as pre-match predictors. Existing
outcome-independent feature exports remain available elsewhere in the repo.
For a single ATP/WTA main-tour modeling table, use [`../main_tour/`](../main_tour/README.md).

## What is combined

- Available Sackmann singles records from tournament start dates in 2000 onward,
  preserving source match fields and results, including labeled nonstandard outcomes.
- The existing verified Valuebetennis crosswalk supplies exact match dates and
  winner/loser-aligned opening and last pre-match prices where available.
- Existing weekly ranking supplements fill only absent/invalid ranks or absent
  points in separate `*_effective` columns, retaining source and snapshot dates.
- Additional supported, completed Valuebetennis results after the archive ends,
  including players that cannot be linked to the Sackmann roster.
- Player profiles from the roster, with existing Wikidata DOB/height supplements
  where the original roster value is missing. These are profile facts observed at
  collection time; height is not guaranteed to describe a player's historic height.

No missing facts are guessed. Blank means unavailable in these inputs, not zero.
No new remote source was scraped to produce this release: it makes the already
collected, attributed source data easier to use and exposes its unresolved gaps.

## Important column rules

| Columns | Meaning |
| --- | --- |
| `record_id` | Original archive content hash, or `vb:` plus provider match ID. Stable primary key. |
| `source_record_id`, `source_file`, `source_row` | Provenance. Archive paths are relative to `data/raw/sackmann-archive/`; provider paths are relative to the repo. |
| `event_date`, `date_precision` | Archive tournament start date or provider match day. Never assume these are interchangeable. |
| `match_date` | Exact day supplied by the verified provider link or recent result; blank otherwise. Timezone is not independently verified. |
| `winner_id`, `loser_id` | Namespaced IDs: `sackmann:atp:…`, `sackmann:wta:…`, or `valuebetennis:<tour>:…`. |
| `source_winner_id`, `source_loser_id` | Original result provider's player IDs. |
| `*_identity_status` | `archive_id`, `crosswalk_verified`, `provider_only`, or `ambiguous_archive_mapping`. Provider-only identities must not be merged by name alone. |
| `category` | Original provider category. Categories from different providers are not asserted to be equivalent. |
| `score` | Winner-first score. Recent provider scores are reversed if their player 2 won. |
| `score_validation` | `source_reported` for archive scores; `score_and_winner_checked` for newly admitted provider results. |
| `*_rank`, `*_rank_points` | Unchanged original match-file values. |
| `*_rank_effective`, `*_rank_points_effective` | Match-file value or existing prior weekly supplement, with separate `*_source` columns. |
| `*_rank_snapshot_date` | YYYYMMDD; supplement strictly before `event_date`, at most 90 days old. Blank for match-file-only values. |
| `odds_*_winner_decimal`, `odds_*_loser_decimal` | Decimal prices greater than 1. Timing labels come from the publisher; this is not a timestamped betting tick archive. |
| `quality_flags` | Semicolon-separated cautions; no flags does not certify every source fact. |
| Other archive fields | Retained unchanged; see [the data model](../../../docs/data-model.md). |

`players.csv.gz` includes full names, handedness, DOB (YYYYMMDD), country code,
height in cm and Wikidata ID where known. DOB and height have explicit sources.
Profile heights outside 100–250 cm are treated as invalid; use an existing valid
Wikidata fallback if available, otherwise leave them blank without guessing units.
Original match-file height fields remain unchanged source observations.
Unmapped provider players have names and provider IDs; unknown biographies stay blank.

`player_identity_candidates.csv.gz` contains one evidence row per recent match where
an unmapped provider ID's exact normalized full name matches exactly one same-tour
archive roster entry. These are explicitly `unverified_name_only`; they are not
merged into the results or player table. Review them before using as aliases. A
matching name alone is not proof that two IDs belong to the same person.

## Admission and exclusions

The archive export rejects missing/equal player IDs and malformed extra CSV cells.
It preserves recorded retirements, walkovers and other outcomes with a quality flag.
Archive score syntax and historical statistics are **not independently adjudicated**.

Recent results require distinct player IDs, a complete supported ordinary singles
score and an agreeing winner. Extra sets after the match is decided, partial scores,
unsupported formats and conflicting winners are excluded. Two-set ATP Grand Slam
scores remain excluded when the source cannot distinguish qualifying from an
unfinished best-of-five match. This intentionally favors precision over coverage.

Already-linked provider rows are not added again. Other provider results must be
more than 14 days after the latest archive tournament start for their tour.
Historical unlinked completed results are listed as `unlinked_within_archive_window`
instead of blindly merged: some may duplicate archive matches. The buffer is a
conservative convention, not a proof of exhaustive cross-source deduplication.

`issues.csv.gz` is an exclusion ledger containing source IDs, dates and reasons.
The original data remains available at the source path. An excluded row is not
necessarily an erroneous match, and the issue count is **not** the number of
missing real-world matches. Complete coverage would need an independent event/draw
census that is not available in this repo.

## Rebuild and preservation

```sh
python scripts/build_dataset.py
python scripts/build_curated_dataset.py
python scripts/verify_curated_dataset.py
```

The builder stages additions and rejects any changed or removed published match
or player row before appending compressed members. Re-running unchanged inputs
does not change match/player file bytes. Existing source CSVs and older exports
are untouched. Sort by date when reading: newly discovered older rows are appended.
Reports and the issue ledger can be regenerated. If an existing interpretation
changes, a documented correction overlay is needed; the builder fails instead of
silently rewriting it.

The daily Action runs this builder and validator after its source update. It can
only add what the configured sources publish; it cannot make missing historical
statistics or missing current results appear.

## Attribution

This combined derivative retains Sackmann / Tennis Abstract's **CC BY-NC-SA 4.0**
terms. Credit **Valuebetennis** for results/prices (**CC BY 4.0**) and **Wikidata
contributors** for enriched structured facts (**CC0**). See [data licensing](../../../DATA_LICENSE.md)
and [odds source notes](../../odds/README.md). Noncommercial use and share-alike
requirements still apply to the combined release.
