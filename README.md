# Tennis History Data

Historical tennis data and a reproducible starting point for match-winner prediction.
This repository contains the source data, not just links or a scraper template.

## Included

- ATP and WTA singles results, major tournaments and team events as recorded by the source.
- ATP qualifying/Challenger records, Futures records, and WTA qualifying/ITF records.
- Player names, source IDs, date of birth, country, handedness, height and Wikidata IDs where supplied.
- Historical rankings and ranking points.
- Historical ATP/WTA singles match odds (2021 onward; separate attributed provider dataset).
- A conservative odds-to-match crosswalk for records with independently agreeing winner and score.
- Match scores, surface, round, draw size, seeds, entries, best-of format, duration, serve and break-point statistics where supplied.
- Archived ATP doubles and older ATP amateur results.
- A locally generated SQLite database, a compressed pre-match feature table split into yearly files, and measured coverage/quality reports.

**Coverage is incomplete, especially in older and lower-tier records.** Read [measured coverage](docs/coverage.md) for observed date ranges and counts. Detailed statistics and player biography fields are often missing. Odds are provided separately and begin in 2021; they are not part of the historical feature table.

## Start here

- Database: `data/processed/tennis.sqlite`
- Model-ready pre-match rows: `data/processed/model_features_by_year/` (150 gzip CSVs, one per year)
- Match odds: `data/odds/atp_wta_match_odds.csv` (opening and last pre-match Pinnacle prices)
- Verified odds/match links: `data/odds/linked_odds_sackmann.csv.gz` (also see its audit report)
- Pre-match model rows with odds: `data/odds/model_features_with_odds.csv.gz` (p1/p2-aligned prices; `p1_won` is the target)
- Pre-event ranking backfills: `data/processed/supplements/ranking_fallbacks.csv.gz` (keyed by `record_id`, weekly snapshots no more than 90 days old)
- Player DOB/height enrichment: `data/processed/supplements/player_profile_enrichment.csv.gz` (only existing Wikidata IDs and missing source fields; CC0 facts)
- Original CSVs: `data/raw/sackmann-archive/atp/` and `wta/`
- Counts and missingness: `data/processed/coverage.csv`, `build_report.json`
- Detailed post-2000 tier/profile completeness: `data/processed/post_2000_coverage_report.json`
- Readable post-2000 coverage summary: `docs/post-2000-coverage.md`
- Baseline scores: `data/processed/feature_report.json`
- Validation results: `data/processed/validation_report.json`

The SQLite database and combined feature export are generated locally and excluded from Git. The yearly feature exports are included for direct use. A fresh Git clone can rebuild them from the tracked source CSVs. `scripts/verify_dataset.py` checks raw-file hashes, temporal feature boundaries, sampled target labels, odds-manifest totals/checksum, and every published odds crosswalk row against the local SQLite archive.

## Rebuild

Python 3.11 or newer; the data pipeline uses only the standard library.

```powershell
# Only needed if the raw CSVs are absent:
python scripts/fetch_sackmann.py

python scripts/build_dataset.py
python scripts/build_features.py
python scripts/partition_features.py
python scripts/build_rank_fallbacks.py
python scripts/fetch_wikidata_profiles.py
python scripts/fetch_valuebetennis_odds.py
python scripts/link_odds_to_sackmann.py
python scripts/build_model_features_with_odds.py
python scripts/verify_dataset.py
python scripts/profile_coverage.py
python -m unittest discover -s tests -v
```

The [daily GitHub Action](.github/workflows/daily-data-update.yml) checks Valuebetennis' published yearly files for missing settled matches from the last 30 days. It appends only unseen match IDs and creates a commit only when new rows are found. Existing rows are never replaced. You can also run it manually from the **Actions** tab and change the lookback window.

The Action updates the raw odds CSV and its manifest only; it does not rebuild the crosswalk or odds-enriched feature export. Those derived odds files must be regenerated and verified after odds or source-feature changes. The pinned match archive/features currently end in June 2026, so newer odds rows do not have archive features to join yet.

Allow several minutes and a few GB of free disk space. A failed database build leaves a staging database for inspection; remove only that generated `data/processed/tennis.building.sqlite` file before retrying.

## Using the data for prediction later

This is a data repository. No trained model is included. The feature export assigns player 1 and player 2 independently of the result and uses `p1_won` as its target. Do not use winner/loser ordering or current-match statistics as pre-match predictors. See [modeling notes](docs/modeling.md) for timing assumptions and limitations.

## Source and reproducibility

Data compiled by **Jeff Sackmann / Tennis Abstract**, retrieved through [Aneeshers' archival mirror](https://github.com/Aneeshers/tennis-sackmann-archive), revision `83733587353df8a41f2fd4f516147d5aa83f5a8d`.
Original license notices and READMEs are retained. `data/source_files.json` records each source CSV's exact SHA-256, size, row count and pinned URL.

Changes made here: exact duplicate match payload removal, normalized SQLite tables with provenance, source-category labels, coverage reports, and derived pre-match features. Raw source CSV bytes are preserved.

## License

Sackmann source and derivatives: **CC BY-NC-SA 4.0**, attribution required, non-commercial use, share-alike; see [DATA_LICENSE.md](DATA_LICENSE.md). The separately sourced Valuebetennis odds file is **CC BY 4.0**; see [its data notes](data/odds/README.md) for attribution.
Project-authored Python code: MIT; see [LICENSE](LICENSE).

