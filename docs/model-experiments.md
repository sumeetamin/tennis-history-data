# Isolated model improvement experiments

Do not mix the following changes when attributing a score change:

1. **Data experiment:** compare the existing ATP/WTA main-tour rows with the
   separate point-history feature supplement. Keep match population, split,
   model family and evaluation code fixed.
2. **Model experiment:** after data is frozen, compare the baseline model with
   a different model or the opponent-adjusted point-history features. Keep
   training rows and temporal splits fixed.
3. **Evaluation experiment:** separately change calibration, scoring or
   uncertainty analysis. Keep data and model fixed.

Use the same chronological train/validation/test boundaries and report the
same eligible match IDs for every comparison. Report coverage and missingness
alongside Brier score, log loss, calibration, and sample counts; use paired
comparisons on the identical held-out matches. Do not let post-match point
aggregates, current-match stats, results, or odds quoted after the chosen
prediction time leak into inputs. No model is trained by the data updater.

`data/experimental/point_history/` is deliberately separate from the existing
pre-match table. The current baseline feature file uses a 28-day history
embargo, and the point archive's crosswalk only supplies tournament start
dates, so its `tournament_start_minus_28_day_proxy` is not a verified
availability time. It is suitable for sensitivity analysis only until exact
match-day or source-availability timestamps are obtained.
The feature file is append-only. Apply the last `feature_corrections.csv.gz`
row for each `record_id` to get the effective feature value; the initial
correction overlay also fixes the first generated ATP/WTA mean that mixed tour
baselines.

The supplement uses a transparent fixed pseudo-point shrinkage (`k=200`) toward
the prior ATP or WTA point-history mean, then an opponent adjustment:

`tour serve mean + player's shrunk serve deviation - opponent's shrunk return deviation`.

This is a reproducible baseline inspired by the use of shrinkage and opponent
adjustment in [Gollub (2021)](https://journals.sagepub.com/doi/10.3233/JSA-200345);
it is **not** a reproduction of that paper's empirical-Bayes estimator.
History is Grand Slam only and not surface-stratified. Measure the resulting
coverage before interpreting model performance.

Injury, fatigue and travel features are not added: the currently used data
sources do not provide reliable, match-specific timestamps proving the
information was known before a prediction time. Add them only when both the
source evidence and its publication/observation time can be audited.
