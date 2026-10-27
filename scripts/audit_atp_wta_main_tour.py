"""Create ATP/WTA main-tour season and tournament coverage audits."""
import csv
import gzip
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/curated/main_tour'
FEATURES = BASE / 'atp_wta_main_tour_model_features.csv.gz'
RESULTS = ROOT / 'data/curated/post_2000/matches'
REPORT = BASE / 'quality_report.json'
SEASONS = BASE / 'season_coverage.csv'
EVENTS = BASE / 'tournament_census.csv.gz'
MAIN_CATEGORIES = {'tour', 'main_tour', 'masters', 'grand_chelem'}

FEATURE_CHECKS = {
    'rank_pair': ('p1_rank', 'p2_rank'),
    'rank_points_pair': ('p1_rank_points', 'p2_rank_points'),
    'age_pair': ('p1_age', 'p2_age'),
    'height_pair': ('p1_ht', 'p2_ht'),
    'hand_pair': ('p1_hand', 'p2_hand'),
    'elo_pair': ('p1_elo', 'p2_elo'),
    'surface_elo_pair': ('p1_surface_elo', 'p2_surface_elo'),
    'prior_win_rate_pair': ('p1_prior_win_rate', 'p2_prior_win_rate'),
    'prior_serve_rate_pair': ('p1_prior_serve_win_rate', 'p2_prior_serve_win_rate'),
    'recent_365_win_rate_pair': ('p1_recent365_win_rate', 'p2_recent365_win_rate'),
    'opening_odds_pair': ('odds_open_p1_decimal', 'odds_open_p2_decimal'),
    'last_pre_match_odds_pair': ('odds_last_pre_match_p1_decimal', 'odds_last_pre_match_p2_decimal'),
    'surface': ('surface',),
    'round': ('round',),
}

EVENT_FIELDS = [
    'tour', 'year', 'source', 'category', 'tourney_id', 'tourney_name',
    'event_date_first', 'event_date_last', 'match_date_first', 'match_date_last',
    'matches', 'unique_players', 'distinct_player_pairs', 'rounds', 'final_round_rows',
    'draw_size_values', 'surface_values', 'exact_match_dates', 'both_ranked',
    'both_serve_stats', 'duration_present', 'opening_odds_pairs', 'last_pre_match_odds_pairs',
    'nonstandard_outcome_rows', 'identity_archive_id_appearances',
    'identity_crosswalk_verified_appearances', 'identity_provider_only_appearances',
]


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def date_text(value):
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except (TypeError, ValueError):
        return ''


def pct(n, d):
    return round(100 * n / d, 2) if d else None


def csv_writer(path, fields, compressed=False):
    pending = path.with_name(path.name + '.pending')
    raw = pending.open('wb')
    if compressed:
        stream = gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0)
        text = io.TextIOWrapper(stream, encoding='utf-8', newline='')
    else:
        text = io.TextIOWrapper(raw, encoding='utf-8', newline='')
    writer = csv.DictWriter(text, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    return writer, text, pending


def finish_csv(text, pending, path):
    text.close()
    pending.replace(path)


def main():
    if not FEATURES.is_file():
        raise SystemExit('Build the main-tour dataset first with scripts/build_main_tour_dataset.py')

    row_counts = Counter()
    coverage = defaultdict(Counter)
    field_presence = defaultdict(Counter)
    issues = Counter()
    issue_examples = defaultdict(list)
    seen_ids = set()
    dates = defaultdict(list)
    eras = defaultdict(Counter)

    with gzip.open(FEATURES, 'rt', encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        feature_fields = reader.fieldnames or []
        for row in reader:
            rid = row.get('record_id', '')
            if not rid or rid in seen_ids:
                issues['duplicate_or_empty_record_id'] += 1
                if len(issue_examples['duplicate_or_empty_record_id']) < 10:
                    issue_examples['duplicate_or_empty_record_id'].append(rid)
            seen_ids.add(rid)
            tour, category = row.get('tour', ''), row.get('category', '').lower()
            event_day = date_text(row.get('event_date', ''))
            if tour not in {'atp', 'wta'} or category not in MAIN_CATEGORIES:
                issues['unexpected_tour_or_category'] += 1
            if not event_day or event_day < '2000-01-01':
                issues['invalid_or_pre_2000_event_date'] += 1
            if row.get('p1_id') == row.get('p2_id') or not row.get('p1_id') or not row.get('p2_id'):
                issues['invalid_player_pair'] += 1
            if row.get('p1_won') not in {'0', '1'}:
                issues['invalid_target'] += 1
            cutoff = date_text(row.get('history_cutoff_exclusive', ''))
            if not cutoff or not event_day or cutoff >= event_day:
                issues['history_cutoff_not_before_event'] += 1
            for side in ('p1', 'p2'):
                latest = date_text(row.get(f'{side}_history_latest_date', ''))
                if latest and cutoff and latest >= cutoff:
                    issues['history_feature_at_or_after_cutoff'] += 1
                snapshot = row.get(f'{side}_rank_snapshot_date', '')
                if snapshot:
                    try:
                        snapshot_day = (datetime.strptime(snapshot, '%Y%m%d').date().isoformat()
                                        if len(snapshot) == 8 and snapshot.isdigit()
                                        else date.fromisoformat(snapshot[:10]).isoformat())
                    except (TypeError, ValueError):
                        issues['invalid_rank_snapshot_date'] += 1
                        if len(issue_examples['invalid_rank_snapshot_date']) < 10:
                            issue_examples['invalid_rank_snapshot_date'].append(rid)
                    else:
                        if event_day and snapshot_day >= event_day:
                            issues['rank_snapshot_not_before_event'] += 1
                for feature in ('rank', 'rank_points'):
                    value = row.get(f'{side}_{feature}', '')
                    if value and positive(value) is None:
                        issues[f'invalid_{feature}_value'] += 1
            for field in ('odds_open_p1_decimal', 'odds_open_p2_decimal',
                          'odds_last_pre_match_p1_decimal', 'odds_last_pre_match_p2_decimal'):
                value = row.get(field, '')
                if value and positive(value) is None:
                    issues['invalid_odds_value'] += 1
            for flag_name, pair_name in (('odds_open_pair_available', 'opening_odds_pair'),
                                         ('odds_last_pre_match_pair_available', 'last_pre_match_odds_pair')):
                expected = all(positive(row.get(field)) for field in FEATURE_CHECKS[pair_name])
                actual = row.get(flag_name) == '1'
                if expected != actual:
                    issues[f'{flag_name}_mismatch'] += 1

            year = event_day[:4] if event_day else ''
            if not year:
                continue
            period = f'{(int(year) // 10) * 10}s' if int(year) < 2020 else '2020s'
            key = (tour, year)
            row_counts[key] += 1
            coverage[(tour, period)]['rows'] += 1
            dates[tour].append(event_day)
            for name, columns in FEATURE_CHECKS.items():
                present = all(bool(row.get(column, '').strip()) for column in columns)
                field_presence[key][name] += int(present)
                coverage[(tour, period)][name] += int(present)

    if not feature_fields:
        raise SystemExit('Main-tour feature file has no header')
    SEASONS.parent.mkdir(parents=True, exist_ok=True)
    season_fields = ['tour', 'season', 'matches']
    for name in FEATURE_CHECKS:
        season_fields += [f'{name}_matches', f'{name}_pct']
    writer, text, pending = csv_writer(SEASONS, season_fields)
    for (tour, year), total in sorted(row_counts.items()):
        record = {'tour': tour, 'season': year, 'matches': total}
        for name in FEATURE_CHECKS:
            count = field_presence[(tour, year)][name]
            record[f'{name}_matches'] = count
            record[f'{name}_pct'] = pct(count, total)
        writer.writerow(record)
    finish_csv(text, pending, SEASONS)

    event_stats = {}
    identity_counts = Counter()
    result_files = sorted(RESULTS.glob('*.csv.gz'))
    result_file_hashes = {}
    for path in result_files:
        result_file_hashes[path.name] = sha256(path)
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                tour = row.get('tour', '')
                category = (row.get('category') or '').lower()
                if tour not in {'atp', 'wta'} or category not in MAIN_CATEGORIES:
                    continue
                try:
                    year = date.fromisoformat((row.get('event_date') or '')[:10]).year
                except ValueError:
                    continue
                source = row.get('source', '')
                event_id = row.get('tourney_id') or row.get('tourney_name') or row.get('source_record_id') or 'unknown'
                key = (tour, year, source, category, event_id)
                item = event_stats.setdefault(key, {
                    'event_dates': [], 'match_dates': [], 'players': set(), 'pairs': set(),
                    'rounds': set(), 'draw_sizes': set(), 'surfaces': set(), 'matches': 0,
                    'finals': 0, 'both_ranked': 0, 'both_serve': 0, 'duration': 0,
                    'open_odds': 0, 'last_odds': 0, 'nonstandard': 0,
                    'archive_id': 0, 'crosswalk_verified': 0, 'provider_only': 0,
                    'name': row.get('tourney_name', ''),
                })
                item['matches'] += 1
                if row.get('event_date'):
                    item['event_dates'].append(row['event_date'])
                if row.get('match_date'):
                    item['match_dates'].append(row['match_date'][:10])
                for side in ('winner', 'loser'):
                    pid = row.get(f'{side}_id', '')
                    if pid:
                        item['players'].add(pid)
                    status = row.get(f'{side}_identity_status', '')
                    if status in {'archive_id', 'crosswalk_verified', 'provider_only'}:
                        item[status if status != 'archive_id' else 'archive_id'] += 1
                w, l = row.get('winner_id', ''), row.get('loser_id', '')
                if w and l:
                    item['pairs'].add(tuple(sorted((w, l))))
                if row.get('round'):
                    item['rounds'].add(row['round'])
                    item['finals'] += row['round'].upper() in {'F', 'FINAL'}
                if row.get('draw_size'):
                    item['draw_sizes'].add(row['draw_size'])
                if row.get('surface'):
                    item['surfaces'].add(row['surface'])
                item['both_ranked'] += bool(positive(row.get('winner_rank_effective')) and positive(row.get('loser_rank_effective')))
                item['both_serve'] += bool(positive(row.get('w_svpt')) and positive(row.get('l_svpt')))
                item['duration'] += bool(positive(row.get('minutes')))
                item['open_odds'] += bool(positive(row.get('odds_open_winner_decimal')) and positive(row.get('odds_open_loser_decimal')))
                item['last_odds'] += bool(positive(row.get('odds_close_winner_decimal')) and positive(row.get('odds_close_loser_decimal')))
                item['nonstandard'] += bool(row.get('quality_flags'))

    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    event_writer, event_text, event_pending = csv_writer(EVENTS, EVENT_FIELDS, compressed=True)
    for (tour, year, source, category, event_id), item in sorted(event_stats.items()):
        event_writer.writerow({
            'tour': tour, 'year': year, 'source': source, 'category': category,
            'tourney_id': event_id, 'tourney_name': item['name'],
            'event_date_first': min(item['event_dates']) if item['event_dates'] else '',
            'event_date_last': max(item['event_dates']) if item['event_dates'] else '',
            'match_date_first': min(item['match_dates']) if item['match_dates'] else '',
            'match_date_last': max(item['match_dates']) if item['match_dates'] else '',
            'matches': item['matches'], 'unique_players': len(item['players']),
            'distinct_player_pairs': len(item['pairs']), 'rounds': ';'.join(sorted(item['rounds'])),
            'final_round_rows': item['finals'], 'draw_size_values': ';'.join(sorted(item['draw_sizes'])),
            'surface_values': ';'.join(sorted(item['surfaces'])), 'exact_match_dates': len(item['match_dates']),
            'both_ranked': item['both_ranked'], 'both_serve_stats': item['both_serve'],
            'duration_present': item['duration'], 'opening_odds_pairs': item['open_odds'],
            'last_pre_match_odds_pairs': item['last_odds'], 'nonstandard_outcome_rows': item['nonstandard'],
            'identity_archive_id_appearances': item['archive_id'],
            'identity_crosswalk_verified_appearances': item['crosswalk_verified'],
            'identity_provider_only_appearances': item['provider_only'],
        })
    finish_csv(event_text, event_pending, EVENTS)

    result_totals = Counter()
    for key, item in event_stats.items():
        tour, year, source, category, _ = key
        result_totals[(tour, source, category, str(year))] += item['matches']
    field_report = {}
    for (tour, period), values in sorted(coverage.items()):
        total = values['rows']
        field_report.setdefault(tour, {})[period] = {
            name: {'matches': values[name], 'pct': pct(values[name], total)} for name in FEATURE_CHECKS
        } | {'matches': total}

    for name, values in issues.items():
        if values and name not in issue_examples:
            issue_examples[name] = []
    report = {
        'schema_version': 1,
        'focus': 'ATP/WTA main-tour singles; event census groups source records by event and does not infer that absent matches are missing.',
        'main_tour_dataset': FEATURES.relative_to(ROOT).as_posix(),
        'main_tour_rows': len(seen_ids),
        'main_tour_sha256': sha256(FEATURES),
        'rows_by_tour': {tour: sum(n for (t, _), n in row_counts.items() if t == tour) for tour in ('atp', 'wta')},
        'date_ranges': {tour: [min(values), max(values)] for tour, values in sorted(dates.items())},
        'feature_availability_by_tour_and_era': field_report,
        'row_validation': {
            'passed': not any(issues.values()),
            'issue_counts': dict(sorted(issues.items())),
            'sample_record_ids': dict(sorted(issue_examples.items())),
        },
        'tournament_census': {
            'path': EVENTS.relative_to(ROOT).as_posix(),
            'event_groups': len(event_stats),
            'result_files': len(result_files),
            'result_files_sha256': result_file_hashes,
            'grouping': 'tour + event year + source + source category + tournament ID; source rows and events are not deduplicated across providers.',
            'completeness_limit': 'Independent annual draw/calendar lists are not available in this repository, so this census reports observed events and match counts; it cannot certify complete tournament coverage or count missing real-world matches.',
        },
        'source_identity_coverage_in_event_census': {
            'archive_id': sum(item['archive_id'] for item in event_stats.values()),
            'crosswalk_verified': sum(item['crosswalk_verified'] for item in event_stats.values()),
            'provider_only': sum(item['provider_only'] for item in event_stats.values()),
        },
        'season_coverage_csv': SEASONS.relative_to(ROOT).as_posix(),
        'season_coverage_sha256': sha256(SEASONS),
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({
        'main_tour_rows': report['main_tour_rows'],
        'rows_by_tour': report['rows_by_tour'],
        'date_ranges': report['date_ranges'],
        'event_groups': len(event_stats),
        'row_validation': report['row_validation'],
    }, indent=2))
    if not report['row_validation']['passed']:
        raise SystemExit('Main-tour quality audit found hard row-level violations; see quality_report.json')


if __name__ == '__main__':
    main()
