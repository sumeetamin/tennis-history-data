# Tennis History Data

Historical tennis data and a reproducible starting point for match-winner prediction.
This repository contains the source data, not just links or a scraper template.

## Included

- ATP and WTA singles results, major tournaments and team events as recorded by the source.
- ATP qualifying/Challenger records, Futures records, and WTA qualifying/ITF records.
- Player names, source IDs, date of birth, country, handedness, height and Wikidata IDs where supplied.
- Historical rankings and ranking points.
- Match scores, surface, round, draw size, seeds, entries, best-of format, duration, serve and break-point statistics where supplied.
- Archived ATP doubles and older ATP amateur results.
- A locally generated SQLite database, a compressed pre-match feature table split into yearly files, and measured coverage/quality reports.

**Coverage is a fixed historical snapshot, not every match ever played.** Read [measured coverage](docs/coverage.md) for actual date ranges and counts. Detailed statistics and player biography fields are often missing. No betting odds, injuries, coaches, tracking coordinates, or live update feed are included.

## Start here

- Database: `data/processed/tennis.sqlite`
- Model-ready pre-match rows: `data/processed/model_features_by_year/` (150 gzip CSVs, one per year)
- Original CSVs: `data/raw/sackmann-archive/atp/` and `wta/`
- Counts and missingness: `data/processed/coverage.csv`, `build_report.json`
- Baseline scores: `data/processed/feature_report.json`
- Validation results: `data/processed/validation_report.json`

The SQLite database and combined feature export are generated locally and excluded from Git. The yearly feature exports are included for direct use. A fresh Git clone can rebuild them from the tracked source CSVs.

## Rebuild

Python 3.11 or newer; the data pipeline uses only the standard library.

```powershell
# Only needed if the raw CSVs are absent:
python scripts/fetch_sackmann.py

python scripts/build_dataset.py
python scripts/build_features.py
python scripts/partition_features.py
python scripts/verify_dataset.py
python -m unittest discover -s tests -v
```

Allow several minutes and a few GB of free disk space. A failed database build leaves a staging database for inspection; remove only that generated `data/processed/tennis.building.sqlite` file before retrying.

## Using the data for prediction later

This is a data repository. No trained model is included. The feature export assigns player 1 and player 2 independently of the result and uses `p1_won` as its target. Do not use winner/loser ordering or current-match statistics as pre-match predictors. See [modeling notes](docs/modeling.md) for timing assumptions and limitations.

## Source and reproducibility

Data compiled by **Jeff Sackmann / Tennis Abstract**, retrieved through [Aneeshers' archival mirror](https://github.com/Aneeshers/tennis-sackmann-archive), revision `83733587353df8a41f2fd4f516147d5aa83f5a8d`.
Original license notices and READMEs are retained. `data/source_files.json` records each source CSV's exact SHA-256, size, row count and pinned URL.

Changes made here: exact duplicate match payload removal, normalized SQLite tables with provenance, source-category labels, coverage reports, and derived pre-match features. Raw source CSV bytes are preserved.

## License

Source and derived tennis data: **CC BY-NC-SA 4.0**, attribution required, non-commercial use, share-alike. See [DATA_LICENSE.md](DATA_LICENSE.md).
Project-authored Python code: MIT; see [LICENSE](LICENSE).

