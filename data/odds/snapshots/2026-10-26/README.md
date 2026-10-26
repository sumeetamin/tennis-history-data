# Audited recent feature snapshot: 2026-10-26

Use `recent_model_features.csv.gz` in this directory for recent-period modeling as of this snapshot. It has **5,739** rows with replayed history and corrected player-aligned prices. Do not concatenate it with the corresponding rows in the older append-only export: they describe the same matches.

The original 5,789-row recent export is retained unchanged for provenance. Full reconstruction with the current crosswalk found:

- 50 rows no longer have an unambiguous provider-player mapping. `excluded_recent_records.json` lists their record IDs and conflicting archive player IDs. They are excluded here rather than assigned an identity by guesswork.
- 2,870 retained rows have different non-price history values under the current source replay. This includes changes in eligibility/mapping and history reconstruction; the audit does not attribute every difference solely to the incremental replay bug.
- Corrected prices match the provider's player ordering; the old odds correction overlay is already reflected in this snapshot.

Player IDs, dates and target labels for all retained rows agree with the older export. Every history date precedes its 28-day cutoff. Ratings are finite, difference columns agree with their player-side values, record IDs are unique, and the row set equals the original IDs minus the 50 explicit exclusions. `manifest.json` records these checks and input/output hashes. The full older-export comparison is `../../recent_history_audit.json`; its `passed: false` describes the older file's disagreement with reconstruction, not failure of the snapshot checks.

The ranking and player-profile supplements in `data/odds/` can be left-joined onto this snapshot by `record_id`; apply their missing-field rules and ignore supplement IDs absent from this snapshot. No model is trained. Source obligations remain Sackmann CC BY-NC-SA 4.0 plus Valuebetennis CC BY 4.0; see the repository data license.

This is a fixed audit snapshot, not a daily feed. The daily append-only file continues to grow and does not retroactively revise old rows. Later source backfills can change what a full reconstruction produces. Exact source publication times are unavailable; this audit establishes consistency with the documented event-date embargo and current source inputs, not independently confirmed historical availability or completeness.

Reconstruction: `python scripts/audit_recent_history.py` rebuilds into a new scratch directory and compares against the original export. It intentionally exits nonzero if differences remain. Compare decompressed records when reproducing this snapshot because gzip container timestamps can differ. Use the source revisions/hashes in the manifest; changing the odds feed or crosswalk can legitimately change reconstruction results.
