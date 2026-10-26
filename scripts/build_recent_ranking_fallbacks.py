"""Append pre-match ranking fills for recent odds-derived feature rows."""
import csv
import gzip
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/processed/tennis.sqlite'
FEATURES = ROOT / 'data/odds/recent_model_features.csv.gz'
OUT = ROOT / 'data/odds/recent_ranking_fallbacks.csv.gz'
REPORT = ROOT / 'data/odds/recent_ranking_fallbacks_report.json'
MAX_AGE_DAYS = 90
FIELDS = ['record_id', 'tour', 'event_date', 'p1_id', 'p2_id',
          'p1_rank_fallback', 'p1_rank_points_fallback', 'p1_rank_snapshot_date', 'p1_rank_age_days',
          'p2_rank_fallback', 'p2_rank_points_fallback', 'p2_rank_snapshot_date', 'p2_rank_age_days']


def sha256(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def positive(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError):
        return None


def main():
    existing = set()
    if OUT.exists():
        with gzip.open(OUT, 'rt', encoding='utf-8', newline='') as src:
            for row in csv.DictReader(src):
                if row['record_id'] in existing:
                    raise ValueError(f'Duplicate recent ranking supplement ID: {row["record_id"]}')
                existing.add(row['record_id'])

    appended = []
    with sqlite3.connect(DB) as db, gzip.open(FEATURES, 'rt', encoding='utf-8', newline='') as src:
        db.execute('CREATE INDEX IF NOT EXISTS rankings_player_date ON rankings(tour,player,ranking_date)')
        latest_ranking_date = db.execute('SELECT max(ranking_date) FROM rankings').fetchone()[0]
        lookup = db.cursor()
        cache = {}
        for feature in csv.DictReader(src):
            record_id = feature['record_id']
            if record_id in existing:
                continue
            event_day = date.fromisoformat(feature['event_date'])
            day_key = event_day.strftime('%Y%m%d')
            result = {field: '' for field in FIELDS}
            result.update(record_id=record_id, tour=feature['tour'], event_date=feature['event_date'],
                          p1_id=feature['p1_id'], p2_id=feature['p2_id'])
            changed = False
            for side in ('p1', 'p2'):
                key = (feature['tour'], feature[f'{side}_id'], day_key)
                if key not in cache:
                    cache[key] = lookup.execute(
                        'SELECT ranking_date,rank,points FROM rankings '
                        'WHERE tour=? AND player=? AND ranking_date<? '
                        'ORDER BY ranking_date DESC LIMIT 1', key,
                    ).fetchone()
                snapshot = cache[key]
                if not snapshot:
                    continue
                snapshot_day = datetime.strptime(snapshot[0], '%Y%m%d').date()
                age = (event_day - snapshot_day).days
                if age < 1 or age > MAX_AGE_DAYS:
                    continue
                if not positive(feature.get(f'{side}_rank')):
                    rank = positive(snapshot[1])
                    if rank is not None:
                        result[f'{side}_rank_fallback'] = int(rank) if rank.is_integer() else rank
                        changed = True
                if not str(feature.get(f'{side}_rank_points') or '').strip():
                    points = positive(snapshot[2])
                    if points is not None:
                        result[f'{side}_rank_points_fallback'] = int(points) if points.is_integer() else points
                        changed = True
                if result[f'{side}_rank_fallback'] or result[f'{side}_rank_points_fallback']:
                    result[f'{side}_rank_snapshot_date'] = snapshot_day.isoformat()
                    result[f'{side}_rank_age_days'] = age
            if changed:
                appended.append(result)
    db.close()

    if appended:
        append_mode = OUT.exists()
        with gzip.open(OUT, 'at' if append_mode else 'wt', encoding='utf-8', newline='', compresslevel=6) as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS)
            if not append_mode:
                writer.writeheader()
            writer.writerows(appended)

    total_rows = 0
    total_counts = Counter()
    totals_by_tour = defaultdict(Counter)
    if OUT.exists():
        with gzip.open(OUT, 'rt', encoding='utf-8', newline='') as src:
            for row in csv.DictReader(src):
                total_rows += 1
                tour = row['tour']
                if row['p1_rank_fallback']:
                    total_counts['rank_fills'] += 1
                    totals_by_tour[tour]['rank_fills'] += 1
                if row['p2_rank_fallback']:
                    total_counts['rank_fills'] += 1
                    totals_by_tour[tour]['rank_fills'] += 1
                if row['p1_rank_points_fallback']:
                    total_counts['rank_points_fills'] += 1
                    totals_by_tour[tour]['rank_points_fills'] += 1
                if row['p2_rank_points_fallback']:
                    total_counts['rank_points_fills'] += 1
                    totals_by_tour[tour]['rank_points_fills'] += 1
                if any(row[f'{side}_{field}_fallback'] for side in ('p1','p2') for field in ('rank','rank_points')):
                    totals_by_tour[tour]['rows'] += 1
    report = {
        'total_rows_with_fallbacks': total_rows,
        'max_snapshot_age_days': MAX_AGE_DAYS,
        'source_latest_ranking_date': latest_ranking_date,
        'rank_fills': total_counts['rank_fills'],
        'rank_points_fills': total_counts['rank_points_fills'],
        'rows_by_tour': {tour: dict(values) for tour, values in sorted(totals_by_tour.items())},
        'sha256': sha256(OUT) if OUT.exists() else None,
        'input_feature_sha256': sha256(FEATURES),
        'input_database_sha256': sha256(DB),
        'supplement_file': 'data/odds/recent_ranking_fallbacks.csv.gz',
        'policy': 'Append-only fallback values; use only for missing rank fields. Snapshot strictly predates the match date and is at most 90 days old. Original recent feature rows are never rewritten.',
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'new_rows_appended': len(appended), **report}, indent=2))


if __name__ == '__main__':
    main()
