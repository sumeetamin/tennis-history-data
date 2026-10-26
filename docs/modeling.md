# Modeling notes

## Target and allowed input columns

For recent-period data through 2026-10-26, prefer the [audited 5,769-row snapshot](../data/odds/snapshots/2026-10-27/README.md). The 5,826-row append-only file has 57 rows that current strict identity checks could not reproduce and 2,872 retained rows whose history differs from full current-source replay. The snapshot already contains corrected odds; join the rank/profile supplements only for IDs present in the snapshot. Do not duplicate rows by combining both versions of the same matches.

The target is `p1_won`. Player ordering uses a deterministic hash of tournament/round/match identifiers and sorted player IDs; the result and score are not used for orientation.

The yearly feature exports in `data/processed/model_features_by_year/` contain the following pre-match inputs:
- Pre-event source rankings/points, ages and heights represented as differences.
- Overall Elo, surface Elo, prior win rates, historical serve-point win rates and recent-year win rates.
- Historical match counts, surface counts and head-to-head history.
- Surface, round, best-of format and match-row handedness.

IDs, names, event dates, split labels and audit dates are metadata, not model inputs. The source database also contains winners, final scores, minutes and current-match serve statistics; those are post-match outcomes and must not become pre-match predictors.

For matches with a strict odds/archive/feature join, `data/odds/model_features_with_odds.csv.gz` adds opening and last pre-match prices oriented to feature `p1` and `p2`. `p1_won` is still the target and must be excluded from predictor columns. Opening odds are appropriate for earlier forecasts; last pre-match odds represent information available only immediately before play. Odds are not available for every row, so report price coverage and compare models on a consistent sample.

`data/odds/recent_model_features.csv.gz` extends the feature table beyond the pinned match archive using settled Valuebetennis results. It currently contains 5,826 rows through 2026-10-26, starting 14 days after the archive's last tournament start date for each tour. It requires each Valuebetennis player ID to map uniquely through an existing strict odds/archive crosswalk and the current player name to match a name observed in that crosswalk. This conservative mapping excludes unverified identities. The features replay archive history and apply the same 28-day embargo; recent feed results enter future history only after that embargo. It includes opening and closing odds, but no ranking, age, height or hand fields from the odds source. It is an append-only gzip CSV; the daily Action adds rows only for new settled match IDs. See `recent_model_features_report.json` for row counts, date range and checksum. Because the archive uses tournament start dates, the 14-day gap is a conservative duplicate guard rather than a formal event-level match.

`data/odds/recent_ranking_fallbacks.csv.gz` adds pre-match ranks and ranking points for eligible recent-feature rows without changing those rows. Join on `record_id` and fill only blanks. Each snapshot is strictly earlier than the match date, at most 90 days old, and has an explicit snapshot date and age. Missing ranks stay missing when no eligible historical snapshot exists.

`data/odds/recent_player_profiles.csv.gz` supplies age-at-match, roster height and handedness for eligible recent rows, also joined by `record_id`. Birth dates and heights include field-level source labels. Age is computed from the date of birth and actual odds-feed match date. Height is a static roster profile value, not a historical measurement; assess whether that is appropriate for the model and avoid treating it as a match-time observation.

## Missing match-time rankings

Before using recent-feature odds, apply `data/odds/recent_odds_corrections.csv` on `record_id`, replacing all four odds columns for every matched correction row, including blanks. This overlay fixes previously published source-player ordering errors; it must not be treated as a blank-only fallback. The existing recent feature CSV remains immutable. The daily builder uses corrected price mapping for future appends, and the correction script verifies every existing row against source prices.

`data/processed/supplements/ranking_fallbacks.csv.gz` contains pre-event weekly ranking values for feature rows whose match-file rank or ranking points are blank/nonpositive. Join it to a feature export on `record_id`; use the fallback only when the corresponding feature value is missing or nonpositive. Player order is already aligned to the feature row's `p1_id` and `p2_id`. Each side has a snapshot date so the fallback can be audited. The snapshot must be strictly earlier than the tournament start date and at most 90 days old. The report gives field counts and both-ranked coverage before and after fallback, by tour and tier.

The odds-enriched feature file applies these ranking fallbacks and includes `p1_rank_source`, `p1_rank_points_source`, `p1_rank_snapshot_date` and the corresponding `p2` fields. `weekly_snapshot` identifies a fallback; `match_record` means the original match row supplied the value; `missing` means neither source supplied it. A filled rank can still be stale relative to an exact match date because the archive usually records tournament start dates, not match timestamps.

`data/processed/supplements/player_profile_enrichment.csv.gz` adds missing/invalid birth dates and heights for roster entries that already have a matching Wikidata ID. Join on `(tour, player_id)`. Its structured facts are CC0; the player IDs are carried from the Sackmann rosters, whose source obligations still apply. This supplement is player metadata and is not automatically added to match features. For age, calculate it from birth date and the historical event date; do not use a present-day age. Height is not verified as a historical measurement for each match.

## Timing

The recent append builder replays every eligible post-archive provider result in event-date/record-ID order, including results whose features were exported by earlier runs. It emits only unseen IDs. This preserves eligible recent history across daily runs; skipping existing IDs before replay would incorrectly omit their results from subsequent Elo, counts, form and head-to-head features. Regression checks compare a single batch against incremental output and cover the 28-day boundary and late-arriving matches. Existing rows are frozen: a result first received late can inform newly exported rows once temporally eligible, but does not retroactively revise previously published feature values. This is an event-date availability approximation, not a reconstructed publication-time feed.

Source dates are generally tournament start dates, not match timestamps. Historical outcomes and serve statistics enter features only when their tournament date is **strictly more than 28 days before** the row's tournament date. All matches from a single edition therefore receive history from before that edition; same-tournament rounds are never fed into one another.

The 28-day lag is a conservative availability assumption for historical match-derived features, not proof of true publication time. The archive lacks exact finish/publication timestamps. Unusually delayed events and retrospective corrections cannot be fully audited. Rankings use source-reported tournament-date values where present; the separate fallback uses only an earlier weekly ranking snapshot. Present-day player roster attributes are not joined into historical model features.

Elo starts at 1500 and uses K=32. Overall and surface Elo are calculated within each tour across the available singles tiers. Within the same historical date, processing order is deterministic by record hash; exact match order is unknown. Elo is an illustrative baseline, not an optimized rating.

Recent365 counts and win rates span the preceding 365 days but exclude the most recent 28 days because of the embargo. Historical serve ratios use sums of recorded valid counts, not means of percentages. Missing statistics remain missing.

## Splits

- Train: event dates before 2022-12-04.
- Purged: 2022-12-04 through 2022-12-31.
- Validation: 2023-01-01 through 2023-12-03.
- Purged: 2023-12-04 through 2023-12-31.
- Test: 2024-01-01 onward.

The purge allows a conservative gap between training labels and evaluation periods. Historical feature state updates as older results become available during validation and test, simulating sequential deployment; the classifier itself is fitted only on training rows. Fit preprocessing on training data only. Tune on validation, leave test untouched, and prefer rolling forward evaluation when expanding the model.

## Exclusions and caveats

Walkovers, retirements, defaults, abandoned/unknown outcomes, invalid dates/player IDs, nonempty surplus CSV cells and conflicting fixture versions are excluded from model rows but retained in the source/database. Conditioning on completed matches changes the target population: this starter does not predict retirement risk or bookmaker settlement outcomes.

The export includes top-tier and lower-tier singles plus older ATP amateur records. Select the population your model is meant to predict, and report scores by tour, level, year and available player history. The example defaults to ATP tour rows. A player with no prior history has Elo 1500, zero counts and missing historical rates.

The data are incomplete, especially for older/lower-tier statistics and biographical details. A frozen archive can contain later corrections to historical records. Results do not establish profitable betting performance; odds cover only a subset, and transaction costs and historical bet executability are not established.

## 2025 consensus odds supplement

`data/odds/model_features_with_consensus_odds_2025.csv.gz` adds a second market source to 4,802 historical feature rows (2,479 ATP, 2,323 WTA). Source season 2025 includes late-December 2024 events, so the builder joins both yearly feature partitions. Historical feature columns are copied unchanged. `odds_2025_*` probabilities and prices are aligned using matched archive player IDs, independently of the result. `p1_won` is still the target; source identifiers, names, and quality flags are audit metadata. Raw source result, score, and `favorite_won` fields are deliberately absent from this model export.

Opening/closing labels are the publisher's claims; the sample has no individual quote timestamps to independently prove those availability times. For an opening-time forecast, omit closing prices/probabilities, line movement, and other close/snapshot-derived market summaries (including bookmaker count and margin). Closing data can only support an immediately-pre-match scenario under the publisher's timing assumption. Fair odds are margin-removed consensus values, not executable bookmaker prices.

Both sources must report a completed match for model inclusion; two archive-feature candidates were omitted because the odds source reports retirement. A best-close price that is nonfinite, at most 1, or more than twice its corresponding fair closing odds flags the whole pair. Both best-close fields are blank for those 82 model rows; source values remain in the raw CSV and audit crosswalk. This is a heuristic anomaly filter, not proof that unflagged prices were executable or pre-match. Counts, hashes and every-row validation results are in the consensus reports under `data/odds/`.

## Validation

Unit checks cover outcome-independent player ordering, the history embargo boundary, tour ID separation and temporal split purging. The full export validator checks source hashes, all feature history dates and a deterministic sample of target labels against the database.

