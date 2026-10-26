"""Export recent, pre-event weekly rankings that fill missing match rank fields.

The supplement is keyed by ``record_id`` and oriented exactly like the model
feature table. It never replaces a positive match-file rank/points value. A
weekly snapshot must be strictly earlier than the tournament start date and no
more than 90 days old.
"""
import csv
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data/processed/tennis.sqlite'
OUT_DIR = ROOT / 'data/processed/supplements'
OUT = OUT_DIR / 'ranking_fallbacks.csv.gz'
REPORT = OUT_DIR / 'ranking_fallbacks_report.json'
MAX_AGE_DAYS = 90


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def positive(value):
    try:
        number = float(value)
        if number <= 0:
            return None
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def present(value):
    return value is not None and str(value).strip() != ''


def oriented_ids(row):
    ids = sorted([row['winner_id'], row['loser_id']])
    key = '|'.join(str(row[k] or '') for k in ('tour', 'tourney_id', 'match_num', 'round')) + '|' + '|'.join(ids)
    if hashlib.sha256(key.encode()).digest()[0] % 2:
        ids.reverse()
    return ids


def ranking_iter(db, tour):
    # The rankings primary key begins (tour, ranking_date, player), so each
    # tour's cursor is already ordered by date without a large external sort.
    return iter(db.execute(
        'SELECT ranking_date,player,rank,points FROM rankings WHERE tour=? ORDER BY ranking_date,player',
        (tour,),
    ))


def main():
    if not DB.is_file():
        raise SystemExit('Build data/processed/tennis.sqlite first with scripts/build_dataset.py')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TEMP TABLE conflicts AS
        SELECT tour,tourney_id,match_num,min(winner_id,loser_id) AS a,
               max(winner_id,loser_id) AS b
        FROM matches
        GROUP BY tour,tourney_id,match_num,min(winner_id,loser_id),max(winner_id,loser_id)
        HAVING count(*)>1""")

    matches = db.execute("""SELECT m.record_id,m.tour,m.category,m.event_date,m.tourney_id,
            m.match_num,m.round,m.winner_id,m.loser_id,m.winner_rank,m.loser_rank,
            m.winner_rank_points,m.loser_rank_points
        FROM matches m
        LEFT JOIN conflicts c ON c.tour=m.tour AND c.tourney_id=m.tourney_id
            AND c.match_num=m.match_num
            AND c.a=min(m.winner_id,m.loser_id) AND c.b=max(m.winner_id,m.loser_id)
        WHERE c.tour IS NULL AND m.source_extra_cells IS NULL
            AND m.event_date IS NOT NULL AND m.winner_id IS NOT NULL AND m.loser_id IS NOT NULL
            AND m.winner_id!=m.loser_id AND m.outcome='completed'
        ORDER BY m.event_date,m.record_id""")

    rank_cursors = {tour: ranking_iter(db, tour) for tour in ('atp', 'wta')}
    rank_next = {tour: next(cursor, None) for tour, cursor in rank_cursors.items()}
    latest = {}
    counts = Counter()
    post_2000 = Counter()
    fields = [
        'record_id', 'tour', 'event_date', 'p1_id', 'p2_id',
        'p1_rank_fallback', 'p1_rank_points_fallback', 'p1_rank_snapshot_date',
        'p2_rank_fallback', 'p2_rank_points_fallback', 'p2_rank_snapshot_date',
    ]
    with gzip.open(OUT, 'wt', encoding='utf-8', newline='', compresslevel=6) as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for row in matches:
            event_day = date.fromisoformat(row['event_date'])
            event_key = event_day.strftime('%Y%m%d')
            for tour, cursor in rank_cursors.items():
                while rank_next[tour] is not None and rank_next[tour][0] < event_key:
                    rank_day, player_id, rank, points = rank_next[tour]
                    latest[(tour, player_id)] = (rank_day, rank, points)
                    rank_next[tour] = next(cursor, None)

            ids = oriented_ids(row)
            raw = {
                row['winner_id']: (row['winner_rank'], row['winner_rank_points']),
                row['loser_id']: (row['loser_rank'], row['loser_rank_points']),
            }
            output = {
                'record_id': row['record_id'], 'tour': row['tour'],
                'event_date': row['event_date'], 'p1_id': ids[0], 'p2_id': ids[1],
            }
            changed = False
            final_ranked = []
            original_ranked = []
            for side, player_id in zip(('p1', 'p2'), ids):
                match_rank, match_points = raw[player_id]
                snapshot = latest.get((row['tour'], player_id))
                snapshot_day = datetime.strptime(snapshot[0], '%Y%m%d').date() if snapshot else None
                usable = bool(snapshot_day and 0 < (event_day - snapshot_day).days <= MAX_AGE_DAYS)
                rank_fallback = None
                points_fallback = None
                original_ranked.append(positive(match_rank) is not None)
                if not positive(match_rank) and usable:
                    rank_fallback = positive(snapshot[1])
                if not present(match_points) and usable:
                    points_fallback = positive(snapshot[2])
                final_ranked.append(positive(match_rank) is not None or rank_fallback is not None)
                output[f'{side}_rank_fallback'] = rank_fallback if rank_fallback is not None else ''
                output[f'{side}_rank_points_fallback'] = points_fallback if points_fallback is not None else ''
                output[f'{side}_rank_snapshot_date'] = snapshot[0] if rank_fallback is not None or points_fallback is not None else ''
                if rank_fallback is not None:
                    counts[(row['tour'], row['category'], 'rank_fills')] += 1
                    if event_day.year >= 2000:
                        post_2000[(row['tour'], row['category'], 'rank_fills')] += 1
                    changed = True
                if points_fallback is not None:
                    counts[(row['tour'], row['category'], 'rank_points_fills')] += 1
                    if event_day.year >= 2000:
                        post_2000[(row['tour'], row['category'], 'rank_points_fills')] += 1
                    changed = True
            both_before = all(original_ranked)
            both_after = all(final_ranked)
            counts[(row['tour'], row['category'], 'eligible_matches')] += 1
            counts[(row['tour'], row['category'], 'both_ranked_before')] += int(both_before)
            counts[(row['tour'], row['category'], 'both_ranked_after')] += int(both_after)
            if event_day.year >= 2000:
                post_2000[(row['tour'], row['category'], 'eligible_matches')] += 1
                post_2000[(row['tour'], row['category'], 'both_ranked_before')] += int(both_before)
                post_2000[(row['tour'], row['category'], 'both_ranked_after')] += int(both_after)
            if changed:
                writer.writerow(output)
                counts[(row['tour'], row['category'], 'matches_with_fallback')] += 1
                if event_day.year >= 2000:
                    post_2000[(row['tour'], row['category'], 'matches_with_fallback')] += 1
                counts['rows'] += 1
            counts['eligible_feature_matches'] += 1

    db.close()
    def nested(counter):
        result = {}
        for (tour, category, metric), value in sorted(counter.items()):
            result.setdefault(tour, {}).setdefault(category, {})[metric] = value
        for tour_rows in result.values():
            for values in tour_rows.values():
                denominator = values.get('eligible_matches', 0)
                if denominator:
                    values['both_ranked_before_pct'] = round(100 * values.get('both_ranked_before', 0) / denominator, 2)
                    values['both_ranked_after_pct'] = round(100 * values.get('both_ranked_after', 0) / denominator, 2)
        return result

    by_tour_category = nested(Counter({key: value for key, value in counts.items() if isinstance(key, tuple)}))
    post_2000_by_tour_category = nested(post_2000)
    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'source': 'Sackmann archive weekly ATP/WTA ranking snapshots; source attribution and CC BY-NC-SA 4.0 terms in DATA_LICENSE.md',
        'policy': {
            'fills_only_missing_or_nonpositive_match_rank': True,
            'fills_only_blank_match_rank_points': True,
            'snapshot_must_precede_event_date': True,
            'maximum_snapshot_age_days': MAX_AGE_DAYS,
            'feature_orientation': 'Same deterministic p1/p2 ID orientation as scripts/build_features.py',
            'eligible_matches': 'Completed, valid-player/date matches included by scripts/build_features.py; duplicate fixture conflicts and extra-cell rows excluded.',
        },
        'eligible_feature_matches': counts['eligible_feature_matches'],
        'rows_with_at_least_one_fallback': counts['rows'],
        'fill_counts_by_tour_and_category': by_tour_category,
        'post_2000_coverage_by_tour_and_category': post_2000_by_tour_category,
        'output': {'path': OUT.relative_to(ROOT).as_posix(), 'rows': counts['rows'], 'bytes': OUT.stat().st_size, 'sha256': sha256(OUT)},
        'input': {'path': DB.relative_to(ROOT).as_posix(), 'sha256': sha256(DB)},
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'eligible_feature_matches': report['eligible_feature_matches'],
        'rows_with_at_least_one_fallback': report['rows_with_at_least_one_fallback'],
        'fill_counts_by_tour_and_category': by_tour_category,
        'post_2000_coverage_by_tour_and_category': post_2000_by_tour_category,
        'output': report['output'],
    }, indent=2))


if __name__ == '__main__':
    main()
