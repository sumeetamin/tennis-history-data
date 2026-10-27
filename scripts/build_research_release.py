"""Publish explicit main-draw and event-level views with no legacy recent rows."""
import csv
import gzip
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path
from build_current_recent_snapshot import sha, write_gzip

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT / 'data/curated/main_tour/atp_wta_main_tour_model_features.csv.gz'
RECENT = ROOT / 'data/odds/recent_main_tour_event_features.csv.gz'
OUT = ROOT / 'data/curated/research_release'
MAIN_ROUNDS = {'R128', 'R64', 'R32', 'R16', 'QF', 'SF', 'F', 'RR', 'BR'}


def read(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def price(value):
    try:
        n = float(value)
        return math.isfinite(n) and n > 1
    except (ValueError, TypeError):
        return False


def normalize(row, recent):
    row = dict(row)
    row['population_source'] = 'current_recent_replay' if recent else 'historical_main_tour_archive'
    row['event_date_basis'] = 'provider_match_date' if recent else 'tournament_start_date_proxy'
    if not recent:
        row['draw_status'] = 'main_draw' if row.get('category') == 'tour' and row.get('round') in MAIN_ROUNDS else 'unknown'
    row['odds_timestamp_verified'] = 'false'
    row['odds_quote_timestamp_utc'] = ''
    row['bookmaker'] = 'Pinnacle' if row.get('odds_provider_match_id') else ''
    row['market'] = 'match_winner' if row.get('odds_provider_match_id') else ''
    for side in ('p1', 'p2'):
        if row.get(f'{side}_hand') not in {'R', 'L', 'A'}:
            row[f'{side}_hand'] = ''
        for field in (f'odds_open_{side}_decimal', f'odds_last_pre_match_{side}_decimal'):
            if not price(row.get(field)):
                row[field] = ''
        if row.get(f'{side}_rank_snapshot_date'):
            age = (date.fromisoformat(row['event_date']) - date.fromisoformat(row[f'{side}_rank_snapshot_date'])).days
            if age < 1 or age > 90:
                raise ValueError(f'Invalid ranking snapshot: {row["record_id"]}')
            row[f'{side}_rank_snapshot_age_days'] = age
            row[f'{side}_rank_is_stale'] = str(age > 14).lower()
        latest = row.get(f'{side}_history_latest_date')
        if latest and latest >= row['history_cutoff_exclusive']:
            raise ValueError(f'History leakage: {row["record_id"]}')
    for stage in ('open', 'last_pre_match'):
        row[f'odds_{stage}_pair_available'] = str(all(price(row.get(f'odds_{stage}_{s}_decimal')) for s in ('p1', 'p2'))).lower()
    if row['p1_won'] not in {'0', '1'} or not row['p1_id'] or row['p1_id'] == row['p2_id']:
        raise ValueError(f'Invalid target or identity: {row["record_id"]}')
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows, seen, skipped_legacy = [], set(), 0
    for source, recent in ((LEGACY, False), (RECENT, True)):
        for row in read(source):
            if not recent and row['record_id'].startswith('vb:'):
                skipped_legacy += 1
                continue
            if row.get('tour') not in {'atp', 'wta'} or row.get('event_date', '') < '2000-01-01':
                continue
            if row['record_id'] in seen:
                raise ValueError(f'Duplicate record: {row["record_id"]}')
            seen.add(row['record_id'])
            rows.append(normalize(row, recent))
    if not rows:
        raise ValueError('Empty release')
    rows.sort(key=lambda r: (r['event_date'], r['tour'], r['record_id']))
    fields = list(dict.fromkeys(key for row in rows for key in row))
    report = {'schema_version': 1, 'legacy_recent_rows_replaced': skipped_legacy,
              'inputs': {p.relative_to(ROOT).as_posix(): sha(p) for p in (LEGACY, RECENT)},
              'files': {}, 'draw_policy': 'Main-draw requires archive tour category and recognized main-draw round, or provider-documented final round 12. Unknown recent rounds are retained only in the event-level view.',
              'timing_policy': 'Historical event dates approximate tournament start. Prior history uses a 28-day embargo. Quote timestamps and actual result availability remain unverified.',
              'completeness': 'Observed source coverage; no independently reconciled official draw census. No claim of all matches or all statistics.'}
    for filename, selected in [('main_tour_event_features.csv.gz', rows),
                               ('main_draw_features.csv.gz', [r for r in rows if r['draw_status'] == 'main_draw'])]:
        path = OUT / filename
        write_gzip(path, fields, ({key: r.get(key, '') for key in fields} for r in selected))
        report['files'][filename] = {'rows': len(selected), 'sha256': sha(path),
            'date_range': [min(r['event_date'] for r in selected), max(r['event_date'] for r in selected)],
            'tour_counts': dict(Counter(r['tour'] for r in selected)),
            'population_source_counts': dict(Counter(r['population_source'] for r in selected)),
            'draw_status_counts': dict(Counter(r['draw_status'] for r in selected))}
    (OUT / 'manifest.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report['files'], indent=2))


if __name__ == '__main__':
    main()
