"""Build an append-only ATP/WTA main-tour pre-match feature release."""
import csv
import gzip
import hashlib
import json
import math
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL = ROOT / 'data/processed/model_features_by_year'
HISTORICAL_ODDS = ROOT / 'data/odds/model_features_with_odds.csv.gz'
RECENT = ROOT / 'data/odds/recent_model_features.csv.gz'
RECENT_RANKS = ROOT / 'data/odds/recent_ranking_fallbacks.csv.gz'
RECENT_PROFILES = ROOT / 'data/odds/recent_player_profiles.csv.gz'
OUT_DIR = ROOT / 'data/curated/main_tour'
OUT = OUT_DIR / 'atp_wta_main_tour_model_features.csv.gz'
REPORT = OUT_DIR / 'manifest.json'

MAIN_CATEGORIES = {'tour', 'main_tour', 'masters', 'grand_chelem'}
BASE_FIELDS = None
RANK_FIELDS = ('p1_rank', 'p1_rank_points', 'p2_rank', 'p2_rank_points',
               'rank_diff', 'rank_points_diff')
RANK_PROVENANCE = ('p1_rank_source', 'p1_rank_points_source', 'p1_rank_snapshot_date',
                   'p2_rank_source', 'p2_rank_points_source', 'p2_rank_snapshot_date')
ODDS_FIELDS = ('odds_provider_match_id', 'odds_match_date_utc',
               'odds_open_p1_decimal', 'odds_open_p2_decimal',
               'odds_last_pre_match_p1_decimal', 'odds_last_pre_match_p2_decimal',
               'odds_open_pair_available', 'odds_last_pre_match_pair_available', 'odds_provider')
PROFILE_PROVENANCE = ('p1_age_source', 'p1_ht_source', 'p1_hand_source',
                      'p2_age_source', 'p2_ht_source', 'p2_hand_source')


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


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


def flag(value):
    return '1' if str(value).strip().lower() in {'1', 'true', 'yes'} else '0'


def source_maps():
    odds = {}
    keep = set(RANK_FIELDS + RANK_PROVENANCE + (
        'odds_provider_match_id', 'odds_match_date_utc',
        'odds_open_p1_decimal', 'odds_open_p2_decimal',
        'odds_last_pre_match_p1_decimal', 'odds_last_pre_match_p2_decimal',
        'odds_open_pair_available', 'odds_last_pre_match_pair_available'))
    for row in read_gzip(HISTORICAL_ODDS):
        odds[row['record_id']] = {name: row.get(name, '') or '' for name in keep}
    ranks = {row['record_id']: row for row in read_gzip(RECENT_RANKS)}
    profiles = {row['record_id']: row for row in read_gzip(RECENT_PROFILES)}
    return odds, ranks, profiles


def output_row(base, historical_odds, recent, rank_fallback, profile_fallback, fields):
    row = {name: base.get(name, '') or '' for name in fields}
    row['tour'] = base['tour'].lower()
    row['category'] = base['category']

    # The historical odds export also contains conservative weekly-rank fallbacks.
    if historical_odds:
        for name in RANK_FIELDS + RANK_PROVENANCE:
            if name in historical_odds:
                row[name] = historical_odds.get(name, '') or ''
        for name in ('odds_provider_match_id', 'odds_match_date_utc',
                     'odds_open_p1_decimal', 'odds_open_p2_decimal',
                     'odds_last_pre_match_p1_decimal', 'odds_last_pre_match_p2_decimal',
                     'odds_open_pair_available', 'odds_last_pre_match_pair_available'):
            row[name] = historical_odds.get(name, '') or ''
        for name in ('odds_open_pair_available', 'odds_last_pre_match_pair_available'):
            row[name] = flag(historical_odds.get(name, ''))
        row['odds_provider'] = 'Valuebetennis' if historical_odds.get('odds_provider_match_id') else ''
    elif recent:
        row['odds_provider_match_id'] = base.get('odds_provider_match_id', '') or ''
        row['odds_match_date_utc'] = base.get('odds_match_date_utc', '') or ''
        row['odds_open_p1_decimal'] = base.get('odds_open_p1_decimal', '') or ''
        row['odds_open_p2_decimal'] = base.get('odds_open_p2_decimal', '') or ''
        row['odds_last_pre_match_p1_decimal'] = base.get('odds_close_p1_decimal', '') or ''
        row['odds_last_pre_match_p2_decimal'] = base.get('odds_close_p2_decimal', '') or ''
        row['odds_provider'] = base.get('odds_provider', '') or ''
        row['odds_open_pair_available'] = str(int(bool(positive(row['odds_open_p1_decimal']) and positive(row['odds_open_p2_decimal']))))
        row['odds_last_pre_match_pair_available'] = str(int(bool(positive(row['odds_last_pre_match_p1_decimal']) and positive(row['odds_last_pre_match_p2_decimal']))))

    for side in ('p1', 'p2'):
        if positive(row.get(f'{side}_rank')) and not row.get(f'{side}_rank_source'):
            row[f'{side}_rank_source'] = 'feature_source' if recent else 'match_file'
        if positive(row.get(f'{side}_rank_points')) and not row.get(f'{side}_rank_points_source'):
            row[f'{side}_rank_points_source'] = 'feature_source' if recent else 'match_file'

    if rank_fallback:
        for side, tag in (('p1', 'p1'), ('p2', 'p2')):
            for field, suffix in (('rank', 'rank_fallback'), ('rank_points', 'rank_points_fallback')):
                column = f'{side}_{field}'
                fallback = rank_fallback.get(f'{tag}_{suffix}', '')
                if not positive(row.get(column)) and positive(fallback):
                    row[column] = fallback
                    row[f'{side}_{field}_source'] = 'weekly_snapshot'
                    row[f'{side}_rank_snapshot_date'] = rank_fallback.get(f'{tag}_rank_snapshot_date', '')
        r1, r2 = positive(row.get('p1_rank')), positive(row.get('p2_rank'))
        q1, q2 = positive(row.get('p1_rank_points')), positive(row.get('p2_rank_points'))
        if r1 is not None and r2 is not None:
            row['rank_diff'] = f'{r1 - r2:g}'
        if q1 is not None and q2 is not None:
            row['rank_points_diff'] = f'{q1 - q2:g}'

    if profile_fallback:
        for side in ('p1', 'p2'):
            for feature, supplemental, source in (
                ('age', f'{side}_age_fallback', f'{side}_birth_date_source'),
                ('ht', f'{side}_ht_fallback', f'{side}_height_source'),
                ('hand', f'{side}_hand_fallback', f'{side}_hand_source'),
            ):
                if not row.get(f'{side}_{feature}') and profile_fallback.get(supplemental):
                    row[f'{side}_{feature}'] = profile_fallback[supplemental]
                    row[f'{side}_{feature}_source'] = profile_fallback.get(source, '')
        for field in ('age_diff', 'height_diff'):
            target = 'age_diff' if field == 'age_diff' else 'ht_diff'
            if not row.get(target) and profile_fallback.get(f'{field}_fallback'):
                row[target] = profile_fallback[f'{field}_fallback']

    return row


def main():
    global BASE_FIELDS
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    years = sorted(HISTORICAL.glob('model_features_*.csv.gz'))
    if not years:
        raise SystemExit(f'No historical feature files found in {HISTORICAL}')
    with gzip.open(years[0], 'rt', encoding='utf-8', newline='') as stream:
        BASE_FIELDS = csv.DictReader(stream).fieldnames
    fields = BASE_FIELDS + list(RANK_PROVENANCE) + list(ODDS_FIELDS) + list(PROFILE_PROVENANCE)
    fields = list(dict.fromkeys(fields))
    odds, ranks, profiles = source_maps()

    existing = {}
    if OUT.exists():
        for row in read_gzip(OUT):
            if list(row) != fields:
                raise ValueError('Published main-tour table schema changed; use a versioned release instead.')
            key = row.get('record_id', '')
            if not key or key in existing:
                raise ValueError(f'Duplicate or empty record_id in published dataset: {key!r}')
            existing[key] = digest([row[name] for name in fields])

    seen = set()
    additions = []
    counts = Counter()
    dates = {}

    def consider(base, is_recent):
        if base.get('tour', '').lower() not in {'atp', 'wta'}:
            return
        if base.get('category', '').lower() not in MAIN_CATEGORIES:
            return
        event_date = base.get('event_date', '')
        if len(event_date) < 4 or not event_date[:4].isdigit() or int(event_date[:4]) < 2000:
            return
        key = base.get('record_id', '')
        if not key or key in seen:
            raise ValueError(f'Duplicate or empty input record_id: {key!r}')
        seen.add(key)
        row = output_row(base, odds.get(key), is_recent, ranks.get(key), profiles.get(key), fields)
        if row.get('p1_won') not in {'0', '1'}:
            raise ValueError(f'Invalid target for {key}: {row.get("p1_won")!r}')
        cutoff = row.get('history_cutoff_exclusive', '')
        event_date = row.get('event_date', '')
        if not cutoff or not event_date or cutoff >= event_date:
            raise ValueError(f'Invalid temporal boundary for {key}: {cutoff!r} >= {event_date!r}')
        old_hash = existing.get(key)
        new_hash = digest([row[name] for name in fields])
        if old_hash and old_hash != new_hash:
            raise ValueError(f'Published row changed for {key}; add a documented correction overlay.')
        counts[(row['tour'], row['category'])] += 1
        dates.setdefault(row['tour'], []).append(event_date)
        if not old_hash:
            additions.append(row)

    for path in years:
        year = int(path.stem.removeprefix('model_features_').removesuffix('.csv'))
        if year < 2000:
            continue
        for base in read_gzip(path):
            consider(base, False)
    if RECENT.exists():
        for base in read_gzip(RECENT):
            consider(base, True)

    if additions:
        pending = OUT_DIR / '.main_tour_append.pending.gz'
        try:
            with gzip.open(pending, 'wt', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
                if not OUT.exists():
                    writer.writeheader()
                writer.writerows(additions)
            if OUT.exists():
                with OUT.open('ab') as destination, pending.open('rb') as source:
                    shutil.copyfileobj(source, destination)
                pending.unlink()
            else:
                pending.replace(OUT)
        finally:
            pending.unlink(missing_ok=True)

    row_count = len(existing) + len(additions)
    report = {
        'schema_version': 1,
        'dataset': OUT.relative_to(ROOT).as_posix(),
        'rows': row_count,
        'tour_rows': {tour: sum(n for (t, _), n in counts.items() if t == tour) for tour in ('atp', 'wta')},
        'tour_category_rows': {f'{tour}:{category}': n for (tour, category), n in sorted(counts.items())},
        'date_ranges': {tour: [min(values), max(values)] for tour, values in sorted(dates.items())},
        'sha256': sha256(OUT),
        'append_policy': 'Existing row content is immutable; only unseen record IDs are appended. New backfills may appear out of date order; sort by event_date when reading.',
        'main_tour_categories': sorted(MAIN_CATEGORIES),
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
