"""Verify the checked-in reconstructed recent-history snapshot against its manifest."""
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT / 'data/odds/snapshots/2026-10-26'
FEATURES = SNAPSHOT_DIR / 'recent_model_features.csv.gz'
EXCLUDED = SNAPSHOT_DIR / 'excluded_recent_records.json'
MANIFEST = SNAPSHOT_DIR / 'manifest.json'
ORIGINAL = ROOT / 'data/odds/recent_model_features.csv.gz'
CORRECTIONS = ROOT / 'data/odds/recent_odds_corrections.csv'
PRICE_FIELDS = ('odds_open_p1_decimal', 'odds_open_p2_decimal', 'odds_close_p1_decimal', 'odds_close_p2_decimal')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    indexed = {row['record_id']: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f'Duplicate record_id in {path}')
    return indexed


def main():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    snapshot = read_gzip(FEATURES)
    original = read_gzip(ORIGINAL)
    excluded = json.loads(EXCLUDED.read_text(encoding='utf-8'))
    excluded_ids = {row['record_id'] for row in excluded}
    if len(excluded_ids) != len(excluded):
        raise ValueError('Duplicate excluded record_id')
    corrections = {}
    with CORRECTIONS.open(encoding='utf-8', newline='') as stream:
        corrections = {row['record_id']: row for row in csv.DictReader(stream)}

    checks = {}
    checks['snapshot_hash'] = digest(FEATURES) == manifest['snapshot_sha256']
    checks['exclusion_hash'] = digest(EXCLUDED) == manifest['excluded_records_sha256']
    checks['row_count'] = len(snapshot) == manifest['rows']
    checks['unique_ids'] = True  # read_gzip rejects duplicates
    checks['id_set'] = set(snapshot) == set(original) - excluded_ids
    checks['excluded_ids_present_in_original'] = excluded_ids <= set(original)

    identity_fields = ('p1_id', 'p2_id', 'event_date', 'p1_won')
    checks['identity_dates_targets_preserved'] = all(
        all(snapshot[rid].get(field) == original[rid].get(field) for field in identity_fields)
        for rid in snapshot
    )
    checks['history_embargo'] = all(
        not row.get(side + '_history_latest_date')
        or row[side + '_history_latest_date'] < row['history_cutoff_exclusive']
        for row in snapshot.values() for side in ('p1', 'p2')
    )
    checks['finite_ratings'] = all(
        math.isfinite(float(row[field]))
        for row in snapshot.values() for field in ('p1_elo', 'p2_elo', 'p1_surface_elo', 'p2_surface_elo')
        if row.get(field)
    )
    nonprice_changed = 0
    price_mismatches = 0
    for rid, row in snapshot.items():
        old = original[rid]
        if any(row.get(field) != old.get(field) for field in old if field not in PRICE_FIELDS):
            nonprice_changed += 1
        correction = corrections.get(rid, old)
        if any(row.get(field) != correction.get(field) for field in PRICE_FIELDS):
            price_mismatches += 1
    checks['history_change_count'] = nonprice_changed == manifest['history_corrected_rows']
    checks['prices_match_corrected_export'] = price_mismatches == 0
    checks['manifest_checks_recorded'] = all(manifest['checks'].values())

    result = {'snapshot': str(FEATURES.relative_to(ROOT)).replace('\\', '/'),
              'rows': len(snapshot), 'excluded_rows': len(excluded),
              'history_changed_rows': nonprice_changed, 'price_mismatches': price_mismatches,
              'checks': checks, 'passed': all(checks.values())}
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise SystemExit('Recent history snapshot verification failed')


if __name__ == '__main__':
    main()
