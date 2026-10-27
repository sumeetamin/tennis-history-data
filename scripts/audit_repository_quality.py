"""Measure current release data directly; fail on integrity defects, disclose source gaps."""
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from build_current_recent_snapshot import sha
from curated_quality import completed_result as settlement_status

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/quality'
FIELDS = ('surface', 'round', 'tourney_level', 'p1_rank', 'p2_rank', 'p1_rank_points', 'p2_rank_points',
          'p1_age', 'p2_age', 'p1_ht', 'p2_ht', 'p1_hand', 'p2_hand',
          'p1_prior_matches', 'p2_prior_matches', 'p1_prior_serve_win_rate', 'p2_prior_serve_win_rate',
          'odds_quote_timestamp_utc')


def available(field, value):
    if value is None or str(value).strip().upper() in {'', 'U', 'UNKNOWN', 'NAN', 'NONE', 'NULL'}:
        return False
    if field.endswith(('_rank', '_rank_points', '_age', '_ht')):
        try:
            number = float(value)
            return math.isfinite(number) and number > 0
        except (ValueError, TypeError):
            return False
    return True


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def bucket(row, suffix, thresholds):
    values = [number(row.get(f'{s}_{suffix}')) for s in ('p1', 'p2')]
    if any(v is None for v in values):
        return 'unknown'
    value = min(values) if suffix == 'prior_matches' else max(values)
    for limit, label in thresholds:
        if value <= limit:
            return label
    return 'above_' + str(thresholds[-1][0])


def measure(path):
    seen, missing, dimensions, failures, days = set(), Counter(), defaultdict(lambda: defaultdict(Counter)), Counter(), []
    odds, ranks_stale, n = Counter(), Counter(), 0
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            n += 1
            rid = row.get('record_id')
            if not rid or rid in seen:
                failures['missing_or_duplicate_record_id'] += 1
            seen.add(rid)
            if not row.get('p1_id') or not row.get('p2_id') or row['p1_id'] == row['p2_id']:
                failures['invalid_identity'] += 1
            if row.get('p1_won') not in {'0', '1'}:
                failures['invalid_target'] += 1
            day = row.get('event_date', '')
            if not day:
                failures['missing_event_date'] += 1
            else:
                days.append(day)
            cutoff = row.get('history_cutoff_exclusive', '')
            if not cutoff or cutoff >= day:
                failures['invalid_history_cutoff'] += 1
            for side in ('p1', 'p2'):
                if row.get(f'{side}_history_latest_date', '') >= cutoff and row.get(f'{side}_history_latest_date'):
                    failures['history_after_cutoff'] += 1
                if str(row.get(f'{side}_rank_is_stale')).lower() == 'true':
                    ranks_stale[side] += 1
            pairs = {}
            for stage in ('open', 'last_pre_match'):
                vals = []
                for side in ('p1', 'p2'):
                    field = f'odds_{stage}_{side}_decimal'
                    value = row.get(field, '')
                    parsed = number(value)
                    valid = parsed is not None and parsed > 1
                    if value and not valid:
                        failures['invalid_decimal_odds'] += 1
                    vals.append(valid)
                pairs[stage] = all(vals)
                odds[stage + '_pair_rows'] += int(all(vals))
            absent = {field for field in FIELDS if not available(field, row.get(field))}
            missing.update(absent)
            groups = {
                'tour': row.get('tour') or 'unknown', 'season': day[:4] or 'unknown',
                'tour_season': (row.get('tour') or 'unknown') + ':' + day[:4],
                'event_level': row.get('competition_group') or row.get('tourney_level') or 'unknown',
                'surface': row.get('surface') or 'unknown', 'draw_status': row.get('draw_status') or 'unknown',
                'ranking': bucket(row, 'rank', [(10, 'both_top10'), (50, 'both_top50'), (100, 'both_top100'), (500, 'both_top500')]),
                'history_depth': bucket(row, 'prior_matches', [(0, 'one_or_both_zero'), (9, 'one_or_both_under10'), (49, 'one_or_both_under50'), (999999, 'both_50plus')]),
                'opening_odds': 'both_available' if pairs['open'] else 'pair_missing',
            }
            for dimension, group in groups.items():
                result = dimensions[dimension][group]
                result['rows'] += 1
                result['opening_pair_rows'] += int(pairs['open'])
                result['last_pre_match_pair_rows'] += int(pairs['last_pre_match'])
                for field in absent:
                    result['missing:' + field] += 1
    return {'rows': n, 'date_range': [min(days), max(days)] if days else [], 'sha256': sha(path),
            'unique_ids': len(seen), 'integrity_failures': dict(failures), 'stale_rank_values_over14_days': dict(ranks_stale),
            'field_missingness': {f: {'missing': missing[f], 'available': n - missing[f],
                'available_pct': round(100 * (n - missing[f]) / n, 2) if n else None} for f in FIELDS},
            'odds': dict(odds), 'dimensions': {d: {k: dict(v) for k, v in sorted(groups.items())} for d, groups in sorted(dimensions.items())}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {
        'recent_enriched': 'data/odds/recent_model_features_enriched.csv.gz',
        'main_draw_release': 'data/curated/research_release/main_draw_features.csv.gz',
        'main_tour_event_release': 'data/curated/research_release/main_tour_event_features.csv.gz',
    }
    reports = {key: dict(path=path, **measure(ROOT / path)) for key, path in sources.items()}
    raw_status, raw_dates, raw_completed = Counter(), [], []
    with (ROOT / 'data/odds/atp_wta_match_odds.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            status = settlement_status(row)
            raw_status[status] += 1
            if row.get('date'):
                raw_dates.append(row['date'][:10])
                if status == 'completed':
                    raw_completed.append(row['date'][:10])
    snapshot = json.loads((ROOT / 'data/odds/current/manifest.json').read_text(encoding='utf-8'))
    report = {
        'schema_version': 1, 'as_of_date': snapshot['as_of_date'], 'datasets': reports,
        'legacy_recent_excluded_rows': snapshot['excluded_recent_rows'], 'replayed_history_changed_rows': snapshot['history_corrected_rows'],
        'raw_provider': {'status_counts': dict(raw_status), 'latest_row_date': max(raw_dates), 'latest_completed_date': max(raw_completed)},
        'checks': {'current_release_integrity': all(not r['integrity_failures'] for r in reports.values()),
                   'independent_match_coverage_denominator': 'unknown', 'exact_historical_odds_quote_timing': 'unavailable',
                   'all_current_main_draw_rounds': 'unresolved', 'all_fields_complete': False},
        'limitations': [
            'No official draw-by-draw independent census; observed counts do not measure all missing matches.',
            'ATP/WTA historical source remains pinned through May/June 2026. Recent providers differ in scope.',
            'Provider opening/last-pre-match Pinnacle prices have no individual quote timestamp.',
            'Recent source round codes have incomplete documented semantics; unknown stages are excluded from confirmed main-draw release.',
            'Rank snapshots are fallbacks up to 90 days old; stale ranks are marked. Profiles are not historical measurements.',
            'Historical event dates and 28-day history embargo approximate availability, not actual published-result timestamps.',
            'No model was trained or evaluated by this data release; no performance or betting-return claim is made.',
        ],
        'rating': 'No numeric completeness rating assigned: missing match denominator and timing evidence prevent a defensible 10/10.'
    }
    (OUT / 'repository_quality.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    lines = ['# Measured repository quality', '', f'As of {report["as_of_date"]}. Rebuild: `python scripts/audit_repository_quality.py`.', '',
             '| Current release | Rows | Date range | Integrity failures |', '|---|---:|---|---:|']
    for name, r in reports.items():
        lines.append(f'| [{name}](../{r["path"]}) | {r["rows"]:,} | {" to ".join(r["date_range"])} | {sum(r["integrity_failures"].values())} |')
    lines += ['', f'Legacy recent rows excluded: {snapshot["excluded_recent_rows"]}; replayed rows with changed non-price fields: {snapshot["history_corrected_rows"]}.',
              f'Latest raw date: {max(raw_dates)}. Latest completed raw match date: {max(raw_completed)}.',
              '', 'Missingness, source hashes, opening/last-pre-match pair counts and breakdowns by tour, season, event level, surface, rank, history depth and draw status are in [the machine-readable audit](../data/quality/repository_quality.json).',
              '', '## Remaining source gaps', '']
    lines += ['- ' + note for note in report['limitations']]
    lines += ['', report['rating'], '']
    (ROOT / 'docs/repository-quality.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print(json.dumps({'rows': {key: r['rows'] for key, r in reports.items()}, 'checks': report['checks']}, indent=2))
    if not report['checks']['current_release_integrity']:
        raise SystemExit('Current release integrity failures; see quality report')


if __name__ == '__main__':
    main()
