"""Rebuild recent rows in scratch storage and compare every published field."""
import csv
import gzip
import hashlib
import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import build_recent_odds_features as builder

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'data/odds/recent_history_audit.json'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    indexed = {row['record_id']: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError('Duplicate feature ID')
    return indexed


def main():
    original_path = builder.OUT
    original_hash = sha(original_path)
    original = read(original_path)
    work = ROOT.parents[1] / 'work'
    work.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix='recent-history-audit-', dir=work))
    builder.OUT = scratch / 'reconstructed.csv.gz'
    builder.REPORT = scratch / 'build_report.json'
    print('Reconstructing recent features in isolated scratch storage', flush=True)
    builder.main()
    reconstructed = read(builder.OUT)
    changed = Counter()
    examples = []
    history_changed_ids = set()
    price_fields = {'odds_open_p1_decimal', 'odds_open_p2_decimal', 'odds_close_p1_decimal', 'odds_close_p2_decimal'}
    with (ROOT / 'data/odds/recent_odds_corrections.csv').open(encoding='utf-8', newline='') as stream:
        corrections = {row['record_id']: row for row in csv.DictReader(stream)}
    corrected_price_differences = 0
    for key in sorted(original.keys() & reconstructed.keys()):
        old, new = original[key], reconstructed[key]
        for field in old:
            if field in price_fields:
                actual = corrections.get(key, old)[field]
                if actual != new[field]:
                    corrected_price_differences += 1
                continue
            if old[field] != new.get(field):
                changed[field] += 1
                history_changed_ids.add(key)
                if len(examples) < 20:
                    examples.append(dict(record_id=key, field=field, published=old[field], reconstructed=new.get(field)))
    missing = sorted(original.keys() - reconstructed.keys())
    preserved = sha(original_path) == original_hash
    result = dict(audited_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                  published_rows=len(original), reconstructed_rows=len(reconstructed),
                  published_rows_missing_from_reconstruction=missing,
                  additional_reconstructed_rows=len(reconstructed.keys() - original.keys()),
                  nonprice_changed_rows=len(history_changed_ids), nonprice_changed_fields=dict(changed), examples=examples,
                  price_differences_after_correction_overlay=corrected_price_differences,
                  original_bytes_preserved=preserved,
                  inputs={'published_features_sha256': original_hash, 'odds_sha256': sha(builder.ODDS),
                          'database_sha256': sha(builder.DB), 'crosswalk_sha256': sha(builder.CROSSWALK),
                          'builder_sha256': sha(Path(builder.__file__)),
                          'history_algorithm_sha256': sha(ROOT / 'scripts/build_features.py'),
                          'odds_mapping_sha256': sha(ROOT / 'scripts/recent_odds_mapping.py'),
                          'correction_sha256': sha(ROOT / 'data/odds/recent_odds_corrections.csv')},
                  passed=not missing and not changed and corrected_price_differences == 0 and preserved,
                  scope='Full field comparison against corrected single-batch replay of current sources; prices compared after correction overlay. This verifies replay consistency, not independent historical source accuracy or original publication timing.')
    REPORT.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, indent=2), flush=True)
    if not result['passed']:
        raise SystemExit('Recent history audit found differences; see audit report')


if __name__ == '__main__':
    main()
