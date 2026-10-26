# Modeling notes

## Target and allowed input columns

The target is `p1_won`. Player ordering uses a deterministic hash of tournament/round/match identifiers and sorted player IDs; the result and score are not used for orientation.

The yearly feature exports in `data/processed/model_features_by_year/` contain the following pre-match inputs:
- Pre-event source rankings/points, ages and heights represented as differences.
- Overall Elo, surface Elo, prior win rates, historical serve-point win rates and recent-year win rates.
- Historical match counts, surface counts and head-to-head history.
- Surface, round, best-of format and match-row handedness.

IDs, names, event dates, split labels and audit dates are metadata, not model inputs. The source database also contains winners, final scores, minutes and current-match serve statistics; those are post-match outcomes and must not become pre-match predictors.

For matches with a strict odds/archive/feature join, `data/odds/model_features_with_odds.csv.gz` adds opening and last pre-match prices oriented to feature `p1` and `p2`. `p1_won` is still the target and must be excluded from predictor columns. Opening odds are appropriate for earlier forecasts; last pre-match odds represent information available only immediately before play. Odds are not available for every row, so report price coverage and compare models on a consistent sample.

## Timing

Source dates are generally tournament start dates, not match timestamps. Historical outcomes and serve statistics enter features only when their tournament date is **strictly more than 28 days before** the row's tournament date. All matches from a single edition therefore receive history from before that edition; same-tournament rounds are never fed into one another.

The 28-day lag is a conservative availability assumption, not proof of true publication time. The archive lacks exact finish/publication timestamps. Unusually delayed events and retrospective corrections cannot be fully audited. Rankings are the source's reported rankings at tournament date; present-day player roster attributes are not joined into historical model features.

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

The data are incomplete, especially for older/lower-tier statistics and biographical details. A frozen archive can contain later corrections to historical records. Results do not establish profitable betting performance; odds and costs are absent.

## Validation

Unit checks cover outcome-independent player ordering, the history embargo boundary, tour ID separation and temporal split purging. The full export validator checks source hashes, all feature history dates and a deterministic sample of target labels against the database.

