# Post-2000 data completeness

Measured from the pinned archive for event dates on/after 2000-01-01. The archive currently contains **1,255,712** match rows across the tiers listed below. These are source-record counts, not proof that every real-world event is present.

## Match and statistics coverage

| Tour | Category | Matches | Both serve stats | Both ranked | Duration | Surface | Event date range |
|---|---|---:|---:|---:|---:|---:|---|
| atp | futures | 420,895 | 24,227 (5.8%) | 328,974 (78.2%) | 24,576 (5.8%) | 420,895 (100.0%) | 2000-01-01 to 2026-06-01 |
| atp | qual_chall | 191,363 | 133,326 (69.7%) | 183,710 (96.0%) | 129,076 (67.5%) | 191,363 (100.0%) | 2000-01-17 to 2026-06-01 |
| atp | tour | 79,299 | 72,233 (91.1%) | 77,435 (97.7%) | 70,529 (88.9%) | 79,246 (99.9%) | 2000-01-03 to 2026-05-25 |
| wta | qual_itf | 491,441 | 52,760 (10.7%) | 327,999 (66.7%) | 45,870 (9.3%) | 491,441 (100.0%) | 2000-01-03 to 2026-06-02 |
| wta | tour | 72,714 | 47,746 (65.7%) | 69,186 (95.2%) | 25,821 (35.5%) | 72,579 (99.8%) | 2000-01-03 to 2026-05-25 |

“Both serve stats” means both players have positive recorded service points. “Both ranked” means both match-time rank fields are positive before the fallback. “Duration” means minutes are present. Event dates are usually tournament start dates, not exact match dates.

## Pre-event ranking fallback for model features

The keyed supplement contains 51,604 feature rows with at least one rank or ranking-points value recovered from a weekly snapshot. A snapshot must strictly precede the tournament start date and be no more than 90 days old. These counts apply to the completed-match feature export, after its exclusions.

| Tour | Category | Feature matches | Both ranked before | Both ranked with fallback | Rank values filled | Ranking-point values filled |
|---|---|---:|---:|---:|---:|---:|
| atp | futures | 403,435 | 314,509 (77.96%) | 322,694 (79.99%) | 9,994 | 9,993 |
| atp | qual_chall | 184,058 | 176,666 (95.98%) | 177,525 (96.45%) | 915 | 915 |
| atp | tour | 76,488 | 74,696 (97.66%) | 74,813 (97.81%) | 130 | 130 |
| wta | qual_itf | 474,677 | 316,442 (66.66%) | 326,731 (68.83%) | 16,200 | 16,182 |
| wta | tour | 70,324 | 66,841 (95.05%) | 67,095 (95.41%) | 427 | 427 |

The main yearly feature files remain unchanged; join the supplement on `record_id` and use it only to fill blank or nonpositive rank values. The odds-enriched feature file already applies these fallbacks and carries per-player provenance columns.

## Player profile coverage

| Tour | Players appearing since 2000 | Date of birth | Height | Hand | Country | Wikidata ID |
|---|---:|---:|---:|---:|---:|---:|
| atp | 20,813 | 19,493 (93.7%) | 2,929 (14.1%) | 20,804 (100.0%) | 20,808 (100.0%) | 2,754 (13.2%) |
| wta | 21,305 | 17,143 (80.5%) | 1,066 (5.0%) | 21,302 (100.0%) | 21,305 (100.0%) | 2,370 (11.1%) |

Player completeness is measured among unique player IDs appearing in post-2000 archive matches. It is not the percentage of all professional players identified.

## CC0 player-profile supplement

The roster tables above show values present in the pinned archive. A separate supplement uses only existing Wikidata IDs and fills only missing/invalid birth dates or heights. It does not alter the source player files. Birth dates require day precision; heights are converted to centimeters and restricted to 130–230 cm. Conflicting Wikidata values are omitted.

| Tour | Birth dates added | DOB coverage after supplement | Heights added | Height coverage after supplement |
|---|---:|---:|---:|---:|
| atp | 0 | 19,493 (93.7%) | 67 | 2,996 (14.4%) |
| wta | 0 | 17,143 (80.5%) | 131 | 1,197 (5.6%) |

The supplement is keyed by `(tour, player_id)` and is licensed CC0 for Wikidata structured facts; its player IDs are derived from the Sackmann rosters and retain those source obligations. Height is a player profile value, not a historical height-at-match value. See `data/processed/supplements/player_profile_enrichment_report.json` for hashes, revision IDs and field counts.

## Odds coverage

The separately attributed odds CSV contains **470,167** singles rows with dates from 2021-01-01 to 2026-10-27, with 247,884 verified links to archive matches (220,802 have provider score agreement; 27,082 have a blank provider score but an exact event/player match, unique nearest date, and completed archive winner confirmation). This includes 162,425 exact event-title links and 85,459 event-title fallback links. Fallback links require the same tour and normalized player pair, no exact-title candidate, a unique nearest archive date within 14 days, and exact winner plus player-oriented set-score agreement. Ambiguous candidates and source score disagreements remain excluded.
The validation report classifies score states as `{"completed": 271157, "incomplete": 76743, "invalid": 8, "missing_score": 122208, "retirement": 7, "walkover": 1, "winner_disagreement": 42, "winner_id_unresolved": 1}` and currently flags 1 future-dated row(s) as of the last validator run. Filter these rows and nonterminal/unknown score states for modeling.

An odds-enriched pre-match feature file is also available for 239,421 rows. It has 152,668 complete opening-price pairs and 117,203 complete last-pre-match-price pairs, oriented to feature p1/p2.

A separate append-only recent model feature file contains 5,826 rows from 2026-06-16 to 2026-10-26, beyond the pinned archive cutoff. It uses verified player-ID aliases, a 14-day archive-end buffer, and the 28-day feature-history embargo. A keyed weekly-ranking supplement provides 6,122 rank and 6,122 ranking-point values across 3,110 matches, from snapshots strictly before match date and no more than 90 days old. The keyed profile supplement adds 11,119 ages at match date, 7,365 static profile heights, and 11,647 handedness values across 5,826 matches. Height is not a historical measurement.

## Limits

- ITF/Futures and Challenger coverage is uneven; the counts above do not establish complete event coverage.
- Lower-tier serve statistics are sparse, and many height and WTA birth-date values are missing.
- The results/rankings archive is frozen at its pinned source revision. The odds feed is maintained separately by the daily append-only action.
- Regenerate this report after rebuilding the SQLite database and refreshing odds/crosswalk inputs with `python scripts/profile_coverage.py`.

Report source database SHA-256: `70078dd3051b7b6c6ca0ee97a800be3be7be08e7e469cf1a131391366d6b4a7a`.

## Additional 2025 consensus odds

A separate attributed sample contributes 5,791 raw odds rows, 4,957 archive links, and 4,802 aligned model rows. These overlap existing match history and are not additional historical matches. Only 4,720 model rows retain best-close pairs after the documented anomaly filter. Opening/closing timing is publisher-reported, without independently verified quote timestamps. See [odds notes](../data/odds/README.md#2025-consensus-odds-from-multiple-bookmakers) and its source/validation reports.
