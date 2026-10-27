"""Profile published match-data coverage without converting unknowns to zero."""
import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATCH_DIR = ROOT / 'data/curated/post_2000/matches'
FEATURES = ROOT / 'data/curated/main_tour/atp_wta_main_tour_model_features.csv.gz'
PBP_DIR = ROOT / 'data/curated/point_by_point'
OUT_CSV = ROOT / 'data/curated/post_2000/coverage_dimensions.csv'
OUT_JSON = ROOT / 'data/curated/post_2000/coverage_report.json'
OUT_DOC = ROOT / 'docs/coverage-dashboard.md'

METRICS = (
    'surface_known', 'player_ids_both_known', 'ranking_both_known', 'serve_boxscore_both_known',
    'score_known', 'duration_known', 'match_day_known', 'exact_start_time_known',
    'match_timezone_known', 'odds_opening_pair_known', 'odds_closing_pair_known',
    'odds_quote_time_known', 'result_available_timestamp_known', 'source_provenance_known',
    'point_summary_linked', 'point_serve_rate_known', 'point_aces_known',
)
DIMENSIONS = ('record_layer', 'tour', 'season', 'event_level', 'surface', 'draw_population', 'outcome',
              'ranking_availability', 'opening_odds_availability', 'closing_odds_availability',
              'player_history_depth')


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def valid(value):
    return bool((value or '').strip())


def positive(value):
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def draw_population(row):
    category = (row.get('category') or '').casefold()
    tourney_level = (row.get('tourney_level') or '').upper()
    round_name = (row.get('round') or '').upper()
    if round_name == 'Q' or (round_name.startswith('Q') and round_name[1:].isdigit()):
        return 'qualifier'
    if category == 'amateur':
        return 'amateur_historical'
    if category == 'qual_chall' and tourney_level == 'C':
        return 'challenger_main_draw'
    if category == 'futures' or (category == 'qual_itf' and tourney_level not in {'G', 'M', 'P', 'A'}):
        return 'itf_or_futures_main_draw'
    if category in {'tour', 'main_tour', 'masters', 'grand_chelem'}:
        return 'atp_wta_tour_main_draw'
    if category in {'qual_chall', 'qual_itf'}:
        return 'other_lower_tier_or_unclassified'
    return 'unclassified'


def rank_state(row):
    a = positive(row.get('winner_rank_effective') or row.get('winner_rank'))
    b = positive(row.get('loser_rank_effective') or row.get('loser_rank'))
    return 'both' if a and b else ('one' if a or b else 'none')


def odds_state(row, stage):
    if stage == 'opening':
        a, b = row.get('odds_open_winner_decimal'), row.get('odds_open_loser_decimal')
    else:
        a, b = row.get('odds_close_winner_decimal'), row.get('odds_close_loser_decimal')
    return 'both' if positive(a) and positive(b) else ('one' if positive(a) or positive(b) else 'none')


def history_bin(p1, p2):
    try:
        n = min(int(float(p1)), int(float(p2)))
    except (TypeError, ValueError):
        return 'unknown'
    if n == 0:
        return '0'
    if n < 5:
        return '1-4'
    if n < 20:
        return '5-19'
    if n < 50:
        return '20-49'
    return '50+'


def load_point_map():
    link_path = PBP_DIR / 'archive_match_links.csv.gz'
    stats_path = PBP_DIR / 'grand_slam_point_match_stats.csv.gz'
    correction_path = PBP_DIR / 'corrections.csv.gz'
    if not (link_path.exists() and stats_path.exists()):
        return {}
    links = {row['source_match_id']: row for row in read_gzip(link_path)}
    stats = {row['source_match_id']: row for row in read_gzip(stats_path)}
    if correction_path.exists():
        for row in read_gzip(correction_path):
            current = json.loads(row['new_row_json'])
            if row['table_name'] == link_path.name:
                links[row['record_key']] = current
            elif row['table_name'] == stats_path.name:
                stats[row['record_key']] = current
    result = {}
    for source_id, link in links.items():
        record_id = link.get('record_id')
        if record_id and source_id in stats:
            result[record_id] = stats[source_id]
    return result


class Profile:
    def __init__(self):
        self.rows = 0
        self.counts = Counter()

    def add(self, metrics):
        self.rows += 1
        for metric, available in metrics.items():
            self.counts[metric] += bool(available)


def profile_rows():
    point_by_record = load_point_map()
    profiles = defaultdict(Profile)
    overall = Profile()
    by_outcome = Counter()
    tour_populations = defaultdict(Counter)

    def add_record(row, history=None):
        tour = (row.get('tour') or '').lower()
        year = (row.get('event_date') or '')[:4]
        pop = draw_population(row)
        rank = rank_state(row)
        opening = odds_state(row, 'opening')
        closing = odds_state(row, 'closing')
        outcome = (row.get('outcome') or 'unknown').casefold()
        surface = row.get('surface') or 'unknown'
        point = point_by_record.get(row.get('record_id', ''), {})
        metrics = {
            'surface_known': valid(row.get('surface')),
            'player_ids_both_known': valid(row.get('winner_id')) and valid(row.get('loser_id')),
            'ranking_both_known': rank == 'both',
            'serve_boxscore_both_known': positive(row.get('w_svpt')) and positive(row.get('l_svpt')),
            'score_known': valid(row.get('score')),
            'duration_known': positive(row.get('minutes')),
            'match_day_known': valid(row.get('match_date')),
            'exact_start_time_known': False,
            'match_timezone_known': False,
            'odds_opening_pair_known': opening == 'both',
            'odds_closing_pair_known': closing == 'both',
            'odds_quote_time_known': False,
            'result_available_timestamp_known': False,
            'source_provenance_known': valid(row.get('source')) and valid(row.get('source_record_id')),
            'point_summary_linked': bool(point),
            'point_serve_rate_known': bool(point and point.get('player1_serve_points_won_rate') and point.get('player2_serve_points_won_rate')),
            'point_aces_known': bool(point and point.get('player1_aces_available') == '1' and point.get('player2_aces_available') == '1'),
        }
        dimensions = {
            'record_layer': 'post_2000_match_rows',
            'tour': tour or 'unknown', 'season': year or 'unknown',
            'event_level': row.get('tourney_level') or 'unknown',
            'surface': surface, 'draw_population': pop, 'outcome': outcome,
            'ranking_availability': rank, 'opening_odds_availability': opening,
            'closing_odds_availability': closing,
        }
        if history is not None:
            dimensions['player_history_depth'] = history
        overall.add(metrics)
        by_outcome[outcome] += 1
        tour_populations[tour or 'unknown'][pop] += 1
        for dimension, value in dimensions.items():
            profiles[(dimension, str(value))].add(metrics)

    for path in sorted(MATCH_DIR.glob('*.csv.gz')):
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                add_record(row)

    feature_rows = 0
    if FEATURES.exists():
        for row in read_gzip(FEATURES):
            feature_rows += 1
            depth = history_bin(row.get('p1_prior_matches'), row.get('p2_prior_matches'))
            tour = (row.get('tour') or '').lower()
            year = (row.get('event_date') or '')[:4]
            # Features are already one row per completed main-tour singles match.
            metrics = {
                'surface_known': valid(row.get('surface')),
                'player_ids_both_known': valid(row.get('p1_id')) and valid(row.get('p2_id')),
                'ranking_both_known': positive(row.get('p1_rank')) and positive(row.get('p2_rank')),
                'serve_boxscore_both_known': positive(row.get('p1_prior_serve_points')) and positive(row.get('p2_prior_serve_points')),
                'score_known': False, 'duration_known': False,
                'match_day_known': False, 'exact_start_time_known': False,
                'match_timezone_known': False,
                'odds_opening_pair_known': positive(row.get('odds_open_p1_decimal')) and positive(row.get('odds_open_p2_decimal')),
                'odds_closing_pair_known': positive(row.get('odds_last_pre_match_p1_decimal')) and positive(row.get('odds_last_pre_match_p2_decimal')),
                'odds_quote_time_known': False, 'result_available_timestamp_known': False,
                'source_provenance_known': valid(row.get('record_id')),
                'point_summary_linked': False, 'point_serve_rate_known': False, 'point_aces_known': False,
            }
            feature_dims = {
                'record_layer': 'main_tour_feature_rows',
                'player_history_depth': depth, 'tour': tour or 'unknown', 'season': year or 'unknown',
                'event_level': row.get('tourney_level') or 'not_in_feature_schema',
                'surface': row.get('surface') or 'unknown', 'draw_population': 'atp_wta_tour_main_draw',
                'outcome': 'completed_target_population',
                'ranking_availability': 'both' if metrics['ranking_both_known'] else 'one_or_none',
                'opening_odds_availability': 'both' if metrics['odds_opening_pair_known'] else 'one_or_none',
                'closing_odds_availability': 'both' if metrics['odds_closing_pair_known'] else 'one_or_none',
            }
            for dimension, value in feature_dims.items():
                profiles[(dimension, str(value))].add(metrics)

    records = []
    for (dimension, value), profile in sorted(profiles.items()):
        row = {'dimension': dimension, 'dimension_value': value, 'population_rows': profile.rows}
        for metric in METRICS:
            present = profile.counts[metric]
            row[metric + '_rows'] = present
            row[metric + '_missing_rows'] = profile.rows - present
            row[metric + '_present_pct'] = round(100 * present / profile.rows, 4) if profile.rows else ''
        records.append(row)
    return records, overall, feature_rows, by_outcome, tour_populations, len(point_by_record)


def write_atomic_csv(path, fields, rows):
    pending = path.with_name(path.name + '.pending')
    with pending.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    pending.replace(path)


def main():
    records, overall, feature_rows, outcomes, tour_populations, point_links = profile_rows()
    fields = ['dimension', 'dimension_value', 'population_rows']
    for metric in METRICS:
        fields += [metric + '_rows', metric + '_missing_rows', metric + '_present_pct']
    write_atomic_csv(OUT_CSV, fields, records)
    report = {
        'input_match_files': [p.relative_to(ROOT).as_posix() for p in sorted(MATCH_DIR.glob('*.csv.gz'))],
        'input_match_file_count': len(list(MATCH_DIR.glob('*.csv.gz'))),
        'match_rows': overall.rows, 'model_feature_rows': feature_rows,
        'point_by_point_linked_archive_records': point_links,
        'counts_by_outcome': dict(sorted(outcomes.items())),
        'draw_population_rows_by_tour': {tour: dict(sorted(counts.items())) for tour, counts in sorted(tour_populations.items())},
        'measures': records,
        'missingness_rules': {
            'unknown_statistics': 'Blank/unknown values remain missing and are counted as missing; they are never filled with zero.',
            'rankings': 'Both players must have positive match/effective ranking values to count as available.',
            'odds': 'A stage is available only when both players have valid decimal prices greater than 1.',
            'exact_time_fields': 'No source currently provides verified match start timezone, result availability timestamp or individual odds quote timestamps. Date-only match-day coverage is separate.',
            'history_depth': 'Minimum of the two players’ pre-match prior_match counts in the published pre-match main-tour feature table; counts from this feature population only.',
        },
        'date_limitations': [
            'event_date is generally a tournament start date and is not an exact match timestamp.',
            'The Valuebetennis date and opening/last-pre-match labels are provider-reported; quote timestamps and timezone were not provided.',
            'A blank date or timestamp is not inferred from match duration, round, event schedule, or assumed delays.',
        ],
        'coverage_csv': OUT_CSV.relative_to(ROOT).as_posix(),
        'coverage_csv_sha256': hashlib.sha256(OUT_CSV.read_bytes()).hexdigest(),
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    doc = [
        '# Coverage dashboard', '',
        f"Generated from **{overall.rows:,}** post-2000 published match rows and **{feature_rows:,}** main-tour feature rows. Coverage counts are row availability, not proof that every real-world event is present.", '',
        'The machine-readable marginal breakdown is [`coverage_dimensions.csv`](../data/curated/post_2000/coverage_dimensions.csv); the complete report and definitions are in [`coverage_report.json`](../data/curated/post_2000/coverage_report.json). Each row reports population size, field-present rows, missing rows, and percent present for the selected dimension.', '',
        '## Population split', '', '| Tour | Population | Rows |', '|---|---|---:|',
    ]
    for tour, groups in sorted(tour_populations.items()):
        for pop, count in sorted(groups.items()):
            doc.append(f'| {tour} | {pop} | {count:,} |')
    doc += [
        '', '## Timing and known gaps', '',
        '- Exact match start timestamps and local time zones are not present in the result source.',
        '- Odds rows have opening and provider-reported last pre-match prices for two players where available, but not verified individual quote timestamps or a quote time zone.',
        '- Result-publication timestamps are not present. Tournament dates and assumed delays are not substituted for them.',
        '- A missing ranking, score, duration, or statistic remains missing. The dashboard counts its absence explicitly.',
        '- Qualifiers, Challenger main draws, Futures/ITF main draws, WTA ITF rows, and tour main draws are measured in separate population categories where source fields permit classification.',
        '', f"Report CSV SHA-256: `{report['coverage_csv_sha256']}`.",
    ]
    OUT_DOC.write_text('\n'.join(doc) + '\n', encoding='utf-8')
    print(json.dumps({
        'match_rows': overall.rows, 'feature_rows': feature_rows,
        'coverage_dimensions': len(records), 'point_by_point_linked_archive_records': point_links,
        'outputs': [OUT_CSV.relative_to(ROOT).as_posix(), OUT_JSON.relative_to(ROOT).as_posix(), OUT_DOC.relative_to(ROOT).as_posix()],
    }, indent=2))


if __name__ == '__main__':
    main()
