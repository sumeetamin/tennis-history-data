"""Build a separate prior-only, point-history feature experiment; never train a model."""
import csv
import gzip
import hashlib
import json
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / 'data/curated/main_tour/atp_wta_main_tour_model_features.csv.gz'
POINT_DIR = ROOT / 'data/curated/point_by_point'
OUT = ROOT / 'data/experimental/point_history/point_history_pre_match_features.csv.gz'
CORRECTIONS = ROOT / 'data/experimental/point_history/feature_corrections.csv.gz'
REPORT = ROOT / 'data/experimental/point_history/report.json'
K = 200.0  # fixed pseudo-points for a transparent, intentionally simple shrinkage baseline
CORRECTION_FIELDS = ['record_id', 'corrected_at_utc', 'old_row_sha256', 'new_row_sha256', 'new_row_json']


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def feature_player_id(tour, canonical_id):
    prefix = f'sackmann:{tour}:'
    return canonical_id[len(prefix):] if canonical_id.startswith(prefix) else canonical_id


def prior_count(sorted_dates, exclusive_cutoff):
    return bisect_left(sorted_dates, exclusive_cutoff)


def row_digest(row, fields):
    body = json.dumps([row.get(name, '') or '' for name in fields], ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(body).hexdigest()


def append_gzip(path, fields, rows):
    rows = list(rows)
    if not rows:
        return
    mode = 'at' if path.exists() else 'wt'
    with gzip.open(path, mode, encoding='utf-8', newline='', compresslevel=9) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        if mode == 'wt':
            writer.writeheader()
        writer.writerows(rows)


def effective_rows(path, key, corrections):
    rows = {row[key]: row for row in read_gzip(path)}
    for correction in corrections:
        if correction['table_name'] == path.name:
            rows[correction['record_key']] = json.loads(correction['new_row_json'])
    return rows


def main():
    corrections_path = POINT_DIR / 'corrections.csv.gz'
    corrections = list(read_gzip(corrections_path)) if corrections_path.exists() else []
    stats = effective_rows(POINT_DIR / 'grand_slam_point_match_stats.csv.gz', 'source_match_id', corrections)
    links = effective_rows(POINT_DIR / 'archive_match_links.csv.gz', 'source_match_id', corrections)

    # Histories are ordered using tournament start dates from the crosswalk. This is a
    # proxy, not a verified match day; the feature table's 28-day embargo remains explicit.
    observations = defaultdict(list)
    matched = 0
    for source_id, link in links.items():
        stat = stats.get(source_id)
        record_id, day, tour = link.get('record_id'), link.get('archive_event_date', ''), link.get('source_tour', '')
        if not stat or not record_id or len(day) < 10 or tour not in {'atp', 'wta'}:
            continue
        matched += 1
        for side, canonical_field in ((1, 'player1_canonical_id'), (2, 'player2_canonical_id')):
            player_id = feature_player_id(tour, link.get(canonical_field, ''))
            serve_n = number(stat.get(f'player{side}_serve_points'))
            serve_w = number(stat.get(f'player{side}_serve_points_won'))
            return_n = number(stat.get(f'player{side}_return_points'))
            return_w = number(stat.get(f'player{side}_return_points_won'))
            if player_id:
                observations[(tour, player_id)].append({
                    'date': day[:10], 'surface': '', 'record_id': record_id,
                    'serve_n': serve_n, 'serve_w': serve_w,
                    'return_n': return_n, 'return_w': return_w,
                })
    for values in observations.values():
        values.sort(key=lambda item: (item['date'], item['record_id']))
    player_index = {}
    for key, values in observations.items():
        dates = [item['date'] for item in values]
        prefix = [[0, 0, 0, 0]]
        for item in values:
            prefix.append([prefix[-1][0] + (item['serve_n'] or 0),
                           prefix[-1][1] + (item['serve_w'] or 0),
                           prefix[-1][2] + (item['return_n'] or 0),
                           prefix[-1][3] + (item['return_w'] or 0)])
        player_index[key] = (dates, prefix)
    tour_index = {}
    for tour in ('atp', 'wta'):
        values = sorted((item for (t, _), group in observations.items() if t == tour for item in group),
                        key=lambda item: (item['date'], item['record_id']))
        dates = [item['date'] for item in values]
        prefix = [[0, 0, 0, 0]]
        for item in values:
            prefix.append([prefix[-1][0] + (item['serve_n'] or 0),
                           prefix[-1][1] + (item['serve_w'] or 0),
                           prefix[-1][2] + (item['return_n'] or 0),
                           prefix[-1][3] + (item['return_w'] or 0)])
        tour_index[tour] = (dates, prefix)

    # Build a prior-only tour-level baseline from all earlier linked Slam observations.
    output_rows = []
    linked_features = 0
    for match in read_gzip(FEATURES):
        cutoff = match.get('history_cutoff_exclusive', '')
        tour = (match.get('tour') or '').lower()
        if tour not in {'atp', 'wta'} or not cutoff:
            continue
        p1, p2 = match.get('p1_id', ''), match.get('p2_id', '')
        # Dates equal to the exclusive cutoff are deliberately excluded.
        p1_dates, p1_prefix = player_index.get((tour, p1), ([], [[0, 0, 0, 0]]))
        p2_dates, p2_prefix = player_index.get((tour, p2), ([], [[0, 0, 0, 0]]))
        n1, n2 = prior_count(p1_dates, cutoff), prior_count(p2_dates, cutoff)
        p1_totals, p2_totals = p1_prefix[n1], p2_prefix[n2]
        base_dates, base_prefix = tour_index[tour]
        baseline_totals = base_prefix[prior_count(base_dates, cutoff)]
        # These are Grand Slam histories only; do not invent surface-adjusted history.
        sv_n, sv_w, ret_n, ret_w = baseline_totals
        serve_base = sv_w / sv_n if sv_n else None
        return_base = ret_w / ret_n if ret_n else None
        values = {'record_id': match.get('record_id', ''), 'tour': tour,
                  'history_cutoff_exclusive': cutoff, 'availability_basis': 'tournament_start_minus_28_day_proxy',
                  'source_scope': 'linked Grand Slam point-by-point matches only; no surface stratification',
                  'p1_prior_pbp_matches': n1, 'p2_prior_pbp_matches': n2,
                  'p1_prior_serve_points': '', 'p1_prior_serve_points_won': '',
                  'p2_prior_serve_points': '', 'p2_prior_serve_points_won': '',
                  'p1_shrunk_serve_rate': '', 'p2_shrunk_serve_rate': '',
                  'p1_shrunk_return_rate': '', 'p2_shrunk_return_rate': '',
                  'tour_prior_serve_rate': f'{serve_base:.8g}' if serve_base is not None else '',
                  'tour_prior_return_rate': f'{return_base:.8g}' if return_base is not None else '',
                  'p1_opponent_adjusted_serve_expectation': '', 'p2_opponent_adjusted_serve_expectation': '',
                  'shrinkage_pseudo_points_k': str(int(K))}
        player_rates = []
        for side, n, totals in ((1, n1, p1_totals), (2, n2, p2_totals)):
            sn, sw, rn, rw = totals
            shrunk_s = (sw + K * serve_base) / (sn + K) if sn and serve_base is not None else None
            shrunk_r = (rw + K * return_base) / (rn + K) if rn and return_base is not None else None
            values[f'p{side}_prior_serve_points'] = str(int(sn)) if sn else ''
            values[f'p{side}_prior_serve_points_won'] = str(int(sw)) if sn else ''
            values[f'p{side}_shrunk_serve_rate'] = f'{shrunk_s:.8g}' if shrunk_s is not None else ''
            values[f'p{side}_shrunk_return_rate'] = f'{shrunk_r:.8g}' if shrunk_r is not None else ''
            player_rates.append((shrunk_s, shrunk_r))
        for side, own, opponent in ((1, player_rates[0], player_rates[1]), (2, player_rates[1], player_rates[0])):
            adjusted = None
            if own[0] is not None and opponent[1] is not None and serve_base is not None and return_base is not None:
                adjusted = serve_base + (own[0] - serve_base) - (opponent[1] - return_base)
            values[f'p{side}_opponent_adjusted_serve_expectation'] = f'{adjusted:.8g}' if adjusted is not None else ''
        if any(rate is not None for pair in player_rates for rate in pair):
            linked_features += 1
        output_rows.append(values)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fields = list(output_rows[0]) if output_rows else []
    pending = OUT.with_name(OUT.name + '.pending')
    old_rows = {row['record_id']: row for row in read_gzip(OUT)} if OUT.exists() else {}
    correction_rows = list(read_gzip(CORRECTIONS)) if CORRECTIONS.exists() else []
    effective = dict(old_rows)
    for row in correction_rows:
        effective[row['record_id']] = json.loads(row['new_row_json'])
    additions, fixes = [], []
    for row in output_rows:
        old = effective.get(row['record_id'])
        if old is None:
            additions.append(row)
            effective[row['record_id']] = row
        elif row_digest(old, fields) != row_digest(row, fields):
            fixes.append({
                'record_id': row['record_id'], 'corrected_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                'old_row_sha256': row_digest(old, fields), 'new_row_sha256': row_digest(row, fields),
                'new_row_json': json.dumps(row, ensure_ascii=False, separators=(',', ':')),
            })
            effective[row['record_id']] = row
    append_gzip(OUT, fields, additions)
    seen_corrections = {(r['record_id'], r['new_row_sha256']) for r in correction_rows}
    new_fixes = [r for r in fixes if (r['record_id'], r['new_row_sha256']) not in seen_corrections]
    append_gzip(CORRECTIONS, CORRECTION_FIELDS, new_fixes)
    if not additions and not new_fixes and OUT.exists() and REPORT.exists():
        print(json.dumps({'status': 'already_current', 'rows': len(effective),
                          'new_rows_appended': 0, 'corrections_appended': 0}, indent=2))
        return
    REPORT.write_text(json.dumps({
        'rows': len(effective), 'new_rows_appended': len(additions), 'corrections_appended': len(new_fixes),
        'rows_with_prior_point_history': linked_features,
        'linked_pbp_matches_in_history': matched, 'source_scope': 'Grand Slam PBP crosswalk only',
        'timing_limit': 'Uses event start date as a proxy and the existing 28-day history cutoff; exact match played times are unavailable.',
        'shrinkage': {'method': 'fixed pseudo-point shrinkage toward prior tour mean', 'k_points': K,
                      'note': 'Transparent sensitivity baseline; not a reproduction of Efron-Morris empirical Bayes.'},
        'opponent_adjustment': 'tour_prior_serve_rate + player_shrunk_serve_deviation - opponent_shrunk_return_deviation',
        'model_training': 'Not performed.', 'generated_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'rows': len(effective), 'new_rows_appended': len(additions),
                      'corrections_appended': len(new_fixes),
                      'rows_with_prior_point_history': linked_features,
                      'linked_pbp_matches': matched}, indent=2))


if __name__ == '__main__':
    main()
