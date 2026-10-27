# ATP and WTA main-tour model features

`atp_wta_main_tour_model_features.csv.gz` is a combined, labeled pre-match feature table for ATP and WTA main-tour singles from 2000 onward. It includes the archive's `tour` category and recent provider categories `main_tour`, `masters`, and `grand_chelem`. Challenger, ITF, qualifying, and team-event rows are not included in this focused release.

The current release has 148,596 rows: 77,315 ATP and 71,281 WTA, with event dates from 2000-01-03 through 2026-10-26 (ATP) and 2026-10-27 (WTA). For field coverage by tour and era, see [`quality_report.json`](quality_report.json) and [`season_coverage.csv`](season_coverage.csv). [`tournament_census.csv.gz`](tournament_census.csv.gz) lists the events represented in the source results. These are observed coverage counts, not estimates of all professional matches.

## Use

- `p1_won` is the binary target (1 means p1 won). It is an outcome label, not an input feature.
- `split` retains the source feature export's historical split label; assign fresh chronological train/validation/test windows for a new experiment.
- Every other field is intended to describe information available before the match. Do not add post-match score, result, serve statistics, or duration from the results release as predictors.
- Rankings and points use existing match-file values, with prior weekly snapshots used only when the source value was missing or invalid. `*_rank_source`, `*_rank_points_source`, and snapshot-date fields show that provenance.
- Profile supplements can fill recent age, height, and handedness only when blank. Source fields identify those additions. Heights are profile values, not historical measurements.
- Odds are optional predictors. Opening prices are provided where available. `odds_last_pre_match_*` is the provider's last reported pre-match price; only use it for a forecast made at that time. Provider timestamps are not independently verified. Blank odds mean unavailable, not zero.
- Rows carry `history_cutoff_exclusive`; the builder rejects a row if its historical feature cutoff is not earlier than the event date. `event_date` may be a tournament start date rather than the exact match day; use the exact match timestamp only where the provider supplies it.
- Player ordering (`p1`/`p2`) is not randomized by the release. For symmetric models, create mirrored training examples or ensure the model does not exploit ordering.

The table combines existing pre-match feature exports with the append-only recent feature feed. It does not claim complete tournament or odds coverage. Historical ATP/WTA match results and statistics remain in `../post_2000/matches/`; player biographies and source limitations are documented there. The event census has no independent expected-event list, so it cannot prove that an event or match is absent.

## Append-only updates

Run `python scripts/build_main_tour_dataset.py` after rebuilding the archive and recent feature supplements, then run `python scripts/audit_atp_wta_main_tour.py`. The builder appends unseen `record_id` values, preserves existing compressed data members, and fails if a previously published feature row changes. New historical backfills may be appended out of date order; sort by `event_date` when reading. `manifest.json` records counts, date ranges, row additions, and the output SHA-256. The daily GitHub Action runs both steps automatically.

## Sources and license

Historical match features derive from the Jeff Sackmann / Tennis Abstract archive and retain its **CC BY-NC-SA 4.0** attribution, non-commercial, and share-alike terms. Recent odds and results come from **Valuebetennis (CC BY 4.0)**. See the repository's `DATA_LICENSE.md` for full attribution and source links. The combined release must not be assumed suitable for commercial use.
