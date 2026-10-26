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

ROOT = Path(__file__).resolve().parents[1]
FEATURE_DIR = ROOT / 'data/processed/model_features_by_year'
DB = ROOT / 'data/processed/tennis.sqlite'
ODDS = ROOT / 'data/odds/atp_wta_match_odds.csv'
CROSSWALK = ROOT / 'data/odds/linked_odds_sackmann.csv.gz'
OUT = ROOT / 'data/odds/model_features_with_odds.csv.gz'
REPORT = ROOT / 'data/odds/model_features_with_odds_report.json'
EXTRA_FIELDS = [
    'odds_provider_match_id', 'odds_match_date_utc',
    'odds_open_p1_decimal', 'odds_open_p2_decimal',
    'odds_last_pre_match_p1_decimal', 'odds_last_pre_match_p2_decimal',
    'odds_open_pair_available', 'odds_last_pre_match_pair_available',
]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    for path in (DB, ODDS, CROSSWALK):
        if not path.is_file():
            raise SystemExit(f'Missing input: {path.relative_to(ROOT)}')

    odds_by_record = {}
    with gzip.open(CROSSWALK, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            record_id = row['sackmann_record_id']
            if record_id in odds_by_record:
                raise ValueError(f'Crosswalk has duplicate archive match ID: {record_id}')
            odds_by_record[record_id] = row

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
    for record_id, row in odds_by_record.items():
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
                    })
                    counts['rows'] += 1
                    counts[f"tour_{feature['tour']}"] += 1
                    counts['opening_pair'] += bool(opening_p1 and opening_p2)
                    counts['last_pre_match_pair'] += bool(closing_p1 and closing_p2)
    if counts['rows'] == 0:
        OUT.unlink(missing_ok=True)
        raise SystemExit('No verified odds links overlap the yearly feature export.')

    missing_features = set(odds_by_record) - seen_features
    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'description': 'Only strictly verified one-to-one odds/archive matches that also occur in the pre-match feature export.',
        'rows': counts['rows'],
        'rows_by_tour': {key.removeprefix('tour_'): value for key, value in sorted(counts.items()) if key.startswith('tour_')},
        'opening_odds_pair_rows': counts['opening_pair'],
        'last_pre_match_odds_pair_rows': counts['last_pre_match_pair'],
        'linked_matches_missing_from_feature_export': len(missing_features),
        'feature_columns': len(writer.fieldnames) - len(EXTRA_FIELDS),
        'odds_columns': EXTRA_FIELDS,
        'output': {'path': OUT.relative_to(ROOT).as_posix(), 'bytes': OUT.stat().st_size, 'sha256': sha256(OUT)},
        'inputs': {
            ODDS.name: sha256(ODDS),
            CROSSWALK.name: sha256(CROSSWALK),
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
