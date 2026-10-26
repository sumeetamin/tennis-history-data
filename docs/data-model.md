# Actual data layout

## Original CSVs
`data/raw/sackmann-archive/` preserves the pinned source files and original documentation. File names follow the source conventions:
- atp_matches_YYYY.csv / wta_matches_YYYY.csv: main tour results.
- atp_matches_qual_chall_YYYY.csv: qualifying and Challenger rows.
- atp_matches_futures_YYYY.csv: Futures/lower-tier rows.
- wta_matches_qual_itf_YYYY.csv: women's ITF and qualifying rows.
- atp_matches_amateur.csv: older ATP historical records.
- atp_matches_doubles_YYYY.csv: archived doubles.
- *_players.csv and *_rankings_*.csv: player profiles and dated rankings.

File category is not a replacement for actual tournament level. Filter `tourney_level` and `round` as well when defining your population.

## SQLite
`data/processed/tennis.sqlite` has tables `matches`, `doubles`, `players`, `rankings`, plus a `tournament_editions` view.

All original source columns are retained as TEXT to preserve source values. Empty strings are normalized to SQL NULL. Explicitly cast numeric columns in analytics queries. Match tables add:
- record_id: SHA-256 of tour plus original payload, used for exact duplicate removal.
- tour: atp or wta; always combine this with a player ID.
- category: source file category.
- source_file / source_row: original filename and 1-based CSV record index (the header counts as record 1).
- event_date: ISO date parsed from tourney_date, generally tournament start.
- outcome: completed / retirement / walkover / default / abandoned / unknown.
- source_extra_cells: JSON of nonempty surplus cells, when a malformed source row has more cells than its header. Surplus empty cells are ignored in the DB while raw files retain them.

The SQLite file is a generated local build artifact and its binary SHA-256 can vary across Python/SQLite versions even when the imported rows are equivalent. Validation therefore checks SQLite integrity and compares source-backed rows and feature outputs directly; the recorded SQLite SHA in older build reports is provenance, not a portable content identity.

Player uniqueness: tour + player_id. Rankings uniqueness: tour + ranking_date + player; first occurrence wins, all source copies remain in raw files.

Match original fields include tournament ID/name, surface, draw size, level, start date, match number, winner/loser IDs, seed, entry, names, hand, height, country, age, ranking, ranking points, score, best_of, round, minutes, and w_/l_ serve statistics. Refer to the preserved upstream matches_data_dictionary.txt for exact field meanings.

The tournament view groups the event identifiers and observed metadata; inconsistent source names or dates may produce multiple rows for one logical event. It is not a fully reconciled historical tournament registry.

## Prediction table
`data/processed/model_features_by_year/` contains 150 gzip CSVs, one per event year, with 1,702,961 eligible completed singles matches total. Fields are documented in modeling.md. Current-match scores, duration and serve outcomes are absent from this pre-match export. `scripts/build_features.py` creates a combined local export; `scripts/partition_features.py` splits it into yearly files.

## Reports
- source_files.json: exact source CSV checksums, sizes, counts, pinned URLs.
- coverage.csv: record counts and ranking/stat coverage by tour, category and year.
- build_report.json: import counts, duplicates, anomalies and database integrity.
- feature_report.json: eligible/excluded counts, temporal splits and Elo baseline.
- validation_report.json: source hash checks and feature chronology/label checks.

