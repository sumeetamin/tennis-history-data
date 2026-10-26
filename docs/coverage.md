# Measured dataset coverage

Source revision: 83733587353df8a41f2fd4f516147d5aa83f5a8d. Counts measured from the imported records.

| Tour | File category | Match records | Earliest event date | Latest event date |
|---|---|---:|---|---|
| atp | amateur | 25,001 | 1877-07-09 | 1967-12-26 |
| atp | futures | 523,355 | 1990-12-29 | 2026-06-01 |
| atp | qual_chall | 240,471 | 1978-01-08 | 2026-06-01 |
| atp | tour | 199,389 | 1967-12-28 | 2026-05-25 |
| wta | qual_itf | 612,532 | 1968-04-22 | 2026-06-02 |
| wta | tour | 162,182 | 1967-12-25 | 2026-05-25 |

These are observed ranges, not proof of complete coverage. Event dates are usually tournament start dates, not exact match dates.
See data/processed/coverage.csv for yearly counts, ranking availability and serve-stat availability.
Post-2000 match-stat and player-profile completeness is summarized in docs/post-2000-coverage.md and data/processed/post_2000_coverage_report.json (generate with scripts/profile_coverage.py).

Player records: 137,483. Ranking records: 5,573,852. Doubles records: 26,399.
Potential conflicting match keys: 0. IDs absent from the master player tables: 0.
Original files preserve every source row. The normalized ranking table keeps the first occurrence of each tour/date/player key.
Exact duplicate match payloads are collapsed; conflicting payloads remain in the database and are excluded from the model export.
Pre-Open Era ATP records are present in the amateur file; this snapshot does not provide a complete pre-1968 history of all majors.
The match archive is a fixed snapshot. Separately attributed settled singles odds from 2021 onward are maintained in data/odds; the daily workflow appends newly published rows without revising existing ones.
