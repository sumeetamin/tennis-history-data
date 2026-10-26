# Daily workflow fresh-checkout check

Checked 2026-10-26 against repository revision `9ffb8e1`, using an isolated local clone with no SQLite database. The daily workflow previously invoked database-dependent feature scripts without creating their ignored database. It now runs `scripts/build_dataset.py` first and allows 30 minutes for the job.

The local rebuild completed with SQLite integrity `ok`: 1,762,930 match rows, 26,399 doubles rows, 137,483 players, and 5,573,852 ranking rows. The database file checksum differed from the older local build; a SQLite file hash identifies a particular physical build, not semantic equality across environments.

The recent feature, ranking, and profile builders completed against the rebuilt database with no new rows. Both the odds-export and recent-supplement validators passed. All four published CSV/gzip datasets retained exactly the same bytes. The odds updater's no-new-record path was exercised with a local semicolon-delimited fixture containing the already imported 72,910 source-season-2026 records. This fixture check does not verify live provider availability.

The new `scripts/verify_daily_append_only.py` compares each dataset against the checked-out Git `HEAD`. Existing bytes must be an exact prefix of the resulting file. Synthetic checks accepted unchanged data and appended rows, and rejected both modified existing rows and truncation. The workflow runs this guard before its commit step. Reports can change independently of the datasets.

This is local Windows/Python verification, not a GitHub-hosted Ubuntu/Python 3.12 run. The GitHub Actions API returned zero workflow runs when inspected. A hosted run is still needed to establish runner timing, network access and commit permissions.

## Recent odds issue and correction

An additional audit found 2,694 recent feature rows with identical exported opening prices despite unequal source prices (among 5,219 rows with unequal populated source opening prices). This identified a need to correct the recent feature builder and supply a keyed correction supplement for previously published rows. Existing timing/hash validators do not establish odds-side correctness. Use the correction overlay described below before using these recent odds columns; the original provider odds remain the authoritative source. This issue does not affect the separately verified 2025 consensus supplement.

The issue is now addressed for future appends by explicit player-side mapping. The keyed `data/odds/recent_odds_corrections.csv` overlay repairs 2,713 existing rows (5,368 prices across opening/closing fields), independently checked against provider names and prices. Apply all four fields, including blanks, to matched `record_id` values. Original feature rows remain unchanged. The daily workflow maintains and verifies the overlay.
