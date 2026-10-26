"""Join verified pre-match odds to the existing pre-match feature rows."""
import csv
import gzip
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from odds_quality import settlement_status

ROOT = Path(__file__).resolve().parents[1]
FEATURE_DIR = ROOT / 'data/processed/model_features_by_year'
DB = ROOT / 'data/processed/tennis.sqlite'
ODDS = ROOT / 'data/odds/atp_wta_match_odds.csv'
CROSSWALK = ROOT / 'data/odds/linked_odds_sackmann.csv.gz'
RANK_FALLBACKS = ROOT / 'data/processed/supplements/ranking_fallbacks.csv.gz'
OUT = ROOT / 'data/odds/model_features_with_odds.csv.gz'
REPORT = ROOT / 'data/odds/model_features_with_odds_report.json'
EXTRA_FIELDS = [
    'odds_provider_match_id', 'odds_match_date_utc',
    'odds_open_p1_decimal', 'odds_open_p2_decimal',
    'odds_last_pre_match_p1_decimal', 'odds_last_pre_match_p2_decimal',
    'odds_open_pair_available', 'odds_last_pre_match_pair_available',
    'p1_rank_source', 'p1_rank_points_source', 'p1_rank_snapshot_date',
    'p2_rank_source', 'p2_rank_points_source', 'p2_rank_snapshot_date',
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    for path in (DB, ODDS, CROSSWALK, RANK_FALLBACKS):
        if not path.is_file():
            raise SystemExit(f'Missing input: {path.relative_to(ROOT)}')

    odds_by_record = {}
    with gzip.open(CROSSWALK, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            record_id = row['sackmann_record_id']
            if record_id in odds_by_record:
                raise ValueError(f'Crosswalk has duplicate archive match ID: {record_id}')
            odds_by_record[record_id] = row

    rank_fallback_by_record = {}
    with gzip.open(RANK_FALLBACKS, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            record_id = row['record_id']
            if record_id in rank_fallback_by_record:
                raise ValueError(f'Rank supplement has duplicate archive match ID: {record_id}')
            rank_fallback_by_record[record_id] = row

    archive_players = {}
    ids = list(odds_by_record)
    with sqlite3.connect(DB) as db:
        for offset in range(0, len(ids), 500):
            chunk = ids[offset:offset + 500]
            marks = ','.join('?' for _ in chunk)
            for record_id, winner_id, loser_id in db.execute(
                    f'SELECT record_id,winner_id,loser_id FROM matches WHERE record_id IN ({marks})', chunk):
                archive_players[record_id] = (str(winner_id), str(loser_id))
    if len(archive_players) != len(odds_by_record):
        raise ValueError(f'{len(odds_by_record)-len(archive_players)} crosswalk records are absent from SQLite')

    oriented_odds = {}
    excluded_odds_states = Counter()
    for record_id, row in odds_by_record.items():
        status = settlement_status(row)
        if status != 'completed':
            excluded_odds_states[status] += 1
            continue
        winner_id, loser_id = archive_players[record_id]
        if row['vainqueur_id'] == row['joueur1_id']:
            provider_p1_id, provider_p2_id = winner_id, loser_id
        elif row['vainqueur_id'] == row['joueur2_id']:
            provider_p1_id, provider_p2_id = loser_id, winner_id
        else:
            raise ValueError(f'Winner ID does not identify either listed player: {row["match_id"]}')
        oriented_odds[record_id] = {
            'row': row,
            'provider_p1_archive_id': provider_p1_id,
            'provider_p2_archive_id': provider_p2_id,
        }

    feature_paths = sorted(
        path for path in FEATURE_DIR.glob('model_features_*.csv.gz')
        if (match := re.fullmatch(r'model_features_(\d{4})\.csv\.gz', path.name)) and int(match.group(1)) >= 2021
    )
    if not feature_paths:
        raise SystemExit('No yearly model feature CSVs for 2021 onward were found.')

    counts = Counter()
    seen_features = set()
    feature_hashes = {}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, 'wt', encoding='utf-8', newline='', compresslevel=6) as target:
        writer = None
        for path in feature_paths:
            feature_hashes[path.name] = sha256(path)
            with gzip.open(path, 'rt', encoding='utf-8', newline='') as source:
                reader = csv.DictReader(source)
                if not reader.fieldnames:
                    raise ValueError(f'Missing feature header: {path.name}')
                if writer is None:
                    writer = csv.DictWriter(target, fieldnames=reader.fieldnames + EXTRA_FIELDS)
                    writer.writeheader()
                elif writer.fieldnames[:len(reader.fieldnames)] != reader.fieldnames:
                    raise ValueError('Yearly feature files have inconsistent column order')

                for feature in reader:
                    record_id = feature['record_id']
                    odds_info = oriented_odds.get(record_id)
                    if odds_info is None:
                        continue
                    if record_id in seen_features:
                        raise ValueError(f'Duplicate feature record ID: {record_id}')
                    seen_features.add(record_id)
                    odds = odds_info['row']
                    p1_id = feature['p1_id']
                    fallback = rank_fallback_by_record.get(record_id)
                    rank_sources = {}
                    for side, player_id in (('p1', feature['p1_id']), ('p2', feature['p2_id'])):
                        if fallback and (fallback['p1_id'] != feature['p1_id'] or fallback['p2_id'] != feature['p2_id']):
                            raise ValueError(f'Rank supplement player orientation disagrees with feature row: {record_id}')
                        for field in ('rank', 'rank_points'):
                            value = feature[f'{side}_{field}']
                            try:
                                has_value = float(value) > 0 if field == 'rank' else bool(value and value.strip())
                            except (TypeError, ValueError):
                                has_value = False
                            source = 'match_record' if has_value else 'missing'
                            fallback_value = fallback.get(f'{side}_{field}_fallback') if fallback else ''
                            if not has_value and fallback_value:
                                feature[f'{side}_{field}'] = fallback_value
                                source = 'weekly_snapshot'
                                counts[f'{field}_fallbacks_applied'] += 1
                            rank_sources[f'{side}_{field}_source'] = source
                        rank_sources[f'{side}_rank_snapshot_date'] = (
                            fallback.get(f'{side}_rank_snapshot_date', '') if fallback else ''
                        )
                    if p1_id == odds_info['provider_p1_archive_id']:
                        opening_p1, opening_p2 = odds['cote1_ouverture'], odds['cote2_ouverture']
                        closing_p1, closing_p2 = odds['cote1_cloture'], odds['cote2_cloture']
                    elif p1_id == odds_info['provider_p2_archive_id']:
                        opening_p1, opening_p2 = odds['cote2_ouverture'], odds['cote1_ouverture']
                        closing_p1, closing_p2 = odds['cote2_cloture'], odds['cote1_cloture']
                    else:
                        raise ValueError(f'Feature player order disagrees with linked match: {record_id}')
                    writer.writerow({
                        **feature,
                        'odds_provider_match_id': odds['match_id'],
                        'odds_match_date_utc': odds['date'],
                        'odds_open_p1_decimal': opening_p1,
                        'odds_open_p2_decimal': opening_p2,
                        'odds_last_pre_match_p1_decimal': closing_p1,
                        'odds_last_pre_match_p2_decimal': closing_p2,
                        'odds_open_pair_available': str(bool(opening_p1 and opening_p2)).lower(),
                        'odds_last_pre_match_pair_available': str(bool(closing_p1 and closing_p2)).lower(),
                        **rank_sources,
                    })
                    counts['rows'] += 1
                    counts['rows_with_rank_fallback'] += bool(
                        'weekly_snapshot' in rank_sources.values()
                    )
                    counts[f"tour_{feature['tour']}"] += 1
                    counts['opening_pair'] += bool(opening_p1 and opening_p2)
                    counts['last_pre_match_pair'] += bool(closing_p1 and closing_p2)
    if counts['rows'] == 0:
        OUT.unlink(missing_ok=True)
        raise SystemExit('No verified odds links overlap the yearly feature export.')

    missing_features = set(oriented_odds) - seen_features
    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'description': 'Only strictly verified one-to-one odds/archive matches with completed feed scores that also occur in the pre-match feature export.',
        'rows': counts['rows'],
        'rows_by_tour': {key.removeprefix('tour_'): value for key, value in sorted(counts.items()) if key.startswith('tour_')},
        'opening_odds_pair_rows': counts['opening_pair'],
        'last_pre_match_odds_pair_rows': counts['last_pre_match_pair'],
        'linked_matches_missing_from_feature_export': len(missing_features),
        'linked_matches_excluded_by_odds_score_state': dict(sorted(excluded_odds_states.items())),
        'feature_columns': len(writer.fieldnames) - len(EXTRA_FIELDS),
        'odds_columns': EXTRA_FIELDS,
        'output': {'path': OUT.relative_to(ROOT).as_posix(), 'bytes': OUT.stat().st_size, 'sha256': sha256(OUT)},
        'rank_fallback_rows_in_odds_features': counts['rows_with_rank_fallback'],
        'rank_fallback_fields_applied': {
            'rank': counts['rank_fallbacks_applied'],
            'rank_points': counts['rank_points_fallbacks_applied'],
        },
        'inputs': {
            ODDS.name: sha256(ODDS),
            CROSSWALK.name: sha256(CROSSWALK),
            RANK_FALLBACKS.relative_to(ROOT).as_posix(): sha256(RANK_FALLBACKS),
            DB.name: sha256(DB),
            'yearly_feature_csv_sha256': feature_hashes,
        },
        'orientation': 'Odds player 1/player 2 prices are mapped to feature p1/p2 by canonical Sackmann player IDs, independent of match outcome ordering.',
        'timing': 'Opening and last pre-match odds are both retained. Use opening prices for earlier forecasts; last pre-match prices are only appropriate for a prediction made immediately before play.',
        'leakage_policy': 'No odds winner ID, score, match duration, or post-match statistics are added. The existing p1_won column remains the supervised target.',
        'license_notes': 'Mixed-source derivative: preserve Sackmann CC BY-NC-SA 4.0 obligations and Valuebetennis CC BY 4.0 attribution; see DATA_LICENSE.md and data/odds/README.md.',
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({
        'rows': report['rows'], 'rows_by_tour': report['rows_by_tour'],
        'opening_pair_rows': report['opening_odds_pair_rows'],
        'last_pre_match_pair_rows': report['last_pre_match_odds_pair_rows'],
        'missing_features': report['linked_matches_missing_from_feature_export'],
        'output': report['output'],
    }, indent=2))


if __name__ == '__main__':
    main()
