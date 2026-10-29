# Measured repository quality

As of 2026-10-29. Rebuild: `python scripts/audit_repository_quality.py`.

| Current release | Rows | Date range | Integrity failures |
|---|---:|---|---:|
| [recent_enriched](../data/odds/recent_model_features_enriched.csv.gz) | 5,853 | 2026-06-16 to 2026-10-29 | 0 |
| [main_draw_release](../data/curated/research_release/main_draw_features.csv.gz) | 146,806 | 2000-01-03 to 2026-10-25 | 0 |
| [main_tour_event_release](../data/curated/research_release/main_tour_event_features.csv.gz) | 148,603 | 2000-01-03 to 2026-10-28 | 0 |

Legacy recent rows excluded: 111; replayed rows with changed non-price fields: 2869.
Latest raw date: 2026-10-29. Latest completed raw match date: 2026-10-29.

Missingness, source hashes, opening/last-pre-match pair counts and breakdowns by tour, season, event level, surface, rank, history depth and draw status are in [the machine-readable audit](../data/quality/repository_quality.json).

## Remaining source gaps

- No official draw-by-draw independent census; observed counts do not measure all missing matches.
- ATP/WTA historical source remains pinned through May/June 2026. Recent providers differ in scope.
- Provider opening/last-pre-match Pinnacle prices have no individual quote timestamp.
- Recent source round codes have incomplete documented semantics; unknown stages are excluded from confirmed main-draw release.
- Rank snapshots are fallbacks up to 90 days old; stale ranks are marked. Profiles are not historical measurements.
- Historical event dates and 28-day history embargo approximate availability, not actual published-result timestamps.
- No model was trained or evaluated by this data release; no performance or betting-return claim is made.

No numeric completeness rating assigned: missing match denominator and timing evidence prevent a defensible 10/10.
