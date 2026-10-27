"""Reconstruct a current research view without changing the append-only archive."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import build_recent_odds_features as builder
from odds_quality import settlement_status
from curated_quality import completed_result

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/odds/current'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        result = {}
        for row in reader:
            key = row.get('record_id')
            if not key or key in result:
                raise ValueError(f'Missing/duplicate record ID: {key}')
            result[key] = row
        return list(reader.fieldnames), result


def write_gzip(path, fields, records):
    pending = path.with_name(path.name + '.pending')
    with pending.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as zipped:
            with io.TextIOWrapper(zipped, encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
                writer.writeheader()
                writer.writerows(records)
    pending.replace(path)


def check_row(row, source, as_of):
    if source is None or completed_result(source) != 'completed':
        raise ValueError(f'Non-completed or absent source: {row["record_id"]}')
    day = date.fromisoformat(row['event_date'])
    if day > as_of or source['date'][:10] != row['event_date']:
        raise ValueError(f'Invalid source date: {row["record_id"]}')
    if not row['p1_id'] or not row['p2_id'] or row['p1_id'] == row['p2_id']:
        raise ValueError(f'Invalid players: {row["record_id"]}')
    cutoff = date.fromisoformat(row['history_cutoff_exclusive'])
    if (day - cutoff).days != 28 or row['p1_won'] not in {'0', '1'}:
        raise ValueError(f'Invalid temporal boundary/target: {row["record_id"]}')
    for side in ('p1', 'p2'):
        latest = row.get(f'{side}_history_latest_date')
        if latest and date.fromisoformat(latest) >= cutoff:
            raise ValueError(f'History leakage: {row["record_id"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    archive_path = builder.OUT
    archive_sha = sha(archive_path)
    _, archive = rows(archive_path)
    with builder.ODDS.open(encoding='utf-8', newline='') as stream:
        raw = {}
        for item in csv.DictReader(stream):
            if not item.get('match_id') or item['match_id'] in raw:
                raise ValueError('Missing or duplicate provider ID')
            raw[item['match_id']] = item
    with tempfile.TemporaryDirectory(prefix='recent-replay-', dir=OUT) as temp:
        old_out, old_report = builder.OUT, builder.REPORT
        try:
            builder.OUT = Path(temp) / 'replay.csv.gz'
            builder.REPORT = Path(temp) / 'replay_report.json'
            builder.main()
            fields, fresh = rows(builder.OUT)
            build_report = json.loads(builder.REPORT.read_text(encoding='utf-8'))
        finally:
            builder.OUT, builder.REPORT = old_out, old_report
    fresh = {key: row for key, row in fresh.items() if date.fromisoformat(row['event_date']) <= args.as_of}
    if not fresh:
        raise ValueError('Empty reconstruction; refusing to replace current snapshot')
    for key, row in fresh.items():
        check_row(row, raw.get(key.removeprefix('vb:')), args.as_of)
    excluded = []
    for key in sorted(archive.keys() - fresh.keys()):
        source = raw.get(key.removeprefix('vb:'))
        status = completed_result(source) if source else 'source_missing'
        reason = status if status != 'completed' else 'not_reproduced_by_current_identity_or_admission_checks'
        excluded.append({'record_id': key, 'event_date': archive[key]['event_date'], 'reason': reason})
    prices = {f'odds_{stage}_{side}_decimal' for stage in ('open', 'close') for side in ('p1', 'p2')}
    changed_fields, changed_ids, changed_history = Counter(), set(), set()
    for key in archive.keys() & fresh.keys():
        for field in fields:
            if archive[key].get(field, '') != fresh[key].get(field, ''):
                changed_fields[field] += 1
                changed_ids.add(key)
                if field not in prices:
                    changed_history.add(key)
    output = OUT / 'recent_model_features.csv.gz'
    write_gzip(output, fields, sorted(fresh.values(), key=lambda r: (r['event_date'], r['record_id'])))
    exclusions_path = OUT / 'excluded_recent_records.json'
    exclusions_path.write_text(json.dumps(excluded, indent=2) + '\n', encoding='utf-8', newline='\n')
    if sha(archive_path) != archive_sha:
        raise ValueError('Original append-only archive changed during reconstruction')
    paths = [builder.ODDS, builder.CROSSWALK, ROOT / 'data/source_files.json',
             Path(builder.__file__), ROOT / 'scripts/build_features.py',
             ROOT / 'scripts/recent_odds_mapping.py', ROOT / 'scripts/odds_quality.py', ROOT / 'scripts/curated_quality.py', Path(__file__)]
    days = [r['event_date'] for r in fresh.values()]
    report = {
        'schema_version': 1, 'as_of_date': args.as_of.isoformat(),
        'data_through': max(days), 'date_range': [min(days), max(days)], 'rows': len(fresh),
        'snapshot_sha256': sha(output), 'source_feature_archive_sha256': archive_sha,
        'published_archive_rows': len(archive), 'excluded_recent_rows': len(excluded),
        'excluded_reasons': dict(Counter(r['reason'] for r in excluded)),
        'excluded_records_sha256': sha(exclusions_path), 'corrected_rows': len(changed_ids),
        'history_corrected_rows': len(changed_history), 'changed_fields': dict(sorted(changed_fields.items())),
        'new_rows_vs_archive': len(fresh.keys() - archive.keys()),
        'skipped_unverified_identity': build_report.get('skipped_unverified_identity'),
        'inputs': {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
        'checks': {'unique_ids': True, 'source_completed': True, 'prior_history_28_day_embargo': True,
                   'original_archive_bytes_preserved': True},
        'scope': 'Replaceable current-source reconstruction; immutable original rows remain in the legacy archive. Event dates and 28-day embargo are availability proxies, not verified result publication timestamps.',
    }
    (OUT / 'manifest.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: report[k] for k in ('rows', 'data_through', 'excluded_recent_rows', 'history_corrected_rows')}, indent=2))


if __name__ == '__main__':
    main()
