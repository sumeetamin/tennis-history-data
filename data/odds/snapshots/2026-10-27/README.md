# Audited recent feature snapshot: 2026-10-27

Use `recent_model_features.csv.gz` for recent-period modeling through **2026-10-26**. It has **5,769** rows with replayed pre-match history and player-aligned odds. Do not concatenate it with the corresponding matches in the append-only recent export.

This rebuild adds 37 rows that were missing from the prior published recent-feature export after the strict identity crosswalk was refreshed. It excludes 57 IDs with ambiguous or missing provider-player mappings under the current crosswalk. Their raw provider records remain in the append-only source export.

The reconstruction recalculates history for 2,872 existing rows. It preserves player IDs, dates and targets; all history dates precede the 28-day cutoff; ratings and difference fields are consistent; and prices match the aligned provider values. See `manifest.json` for hashes and checks, `excluded_recent_records.json` for omitted IDs, and `../../recent_history_audit.json` for the field-level comparison.

Verify the checked-in snapshot and manifest with `python scripts/verify_recent_history_snapshot.py`. Rebuild and compare to current source data with `python scripts/audit_recent_history.py`; that audit intentionally exits nonzero if the older append-only export differs from reconstruction.

This is a fixed snapshot, not a daily feed. The main historical archive remains pinned through June 2026; licensed recent odds/results extend this feature supplement through 2026-10-26. See the repository's source and license notes for attribution and usage terms.
