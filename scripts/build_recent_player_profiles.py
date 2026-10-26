"""Append age-at-match and roster-profile facts for recent odds-derived rows."""
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
PROFILE_ENRICHMENT = ROOT / 'data/processed/supplements/player_profile_enrichment.csv.gz'
OUT = ROOT / 'data/odds/recent_player_profiles.csv.gz'
REPORT = ROOT / 'data/odds/recent_player_profiles_report.json'
FIELDS = ['record_id', 'tour', 'event_date', 'p1_id', 'p2_id']
for side in ('p1', 'p2'):
    FIELDS += [f'{side}_age_fallback', f'{side}_birth_date', f'{side}_birth_date_source',
               f'{side}_ht_fallback', f'{side}_height_source',
               f'{side}_hand_fallback', f'{side}_hand_source']
FIELDS += ['age_diff_fallback', 'height_diff_fallback']


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parse_dob(value):
    value = str(value or '').strip()
    try:
        return datetime.strptime(value, '%Y%m%d').date() if len(value) == 8 else date.fromisoformat(value)
    except ValueError:
        return None


def height_cm(value):
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number.is_integer() and 130 <= number <= 230 else None
    except (TypeError, ValueError):
        return None


def main():
    existing = set()
    if OUT.exists():
        with gzip.open(OUT, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                if row['record_id'] in existing:
                    raise ValueError(f'Duplicate recent player-profile ID: {row["record_id"]}')
                existing.add(row['record_id'])

    wikidata = {}
    with gzip.open(PROFILE_ENRICHMENT, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            wikidata[(row['tour'], row['player_id'])] = row

    appended = []
    player_cache = {}
    recent_feature_rows = 0
    with sqlite3.connect(DB) as db, gzip.open(FEATURES, 'rt', encoding='utf-8', newline='') as stream:
        player_query = db.cursor()
        for feature in csv.DictReader(stream):
            recent_feature_rows += 1
            record_id = feature['record_id']
            if record_id in existing:
                continue
            event_day = date.fromisoformat(feature['event_date'])
            output = {field: '' for field in FIELDS}
            output.update(record_id=record_id, tour=feature['tour'], event_date=feature['event_date'],
                          p1_id=feature['p1_id'], p2_id=feature['p2_id'])
            ages, heights = {}, {}
            changed = False
            for side in ('p1', 'p2'):
                key = (feature['tour'], feature[f'{side}_id'])
                if key not in player_cache:
                    player_cache[key] = player_query.execute(
                        'SELECT hand,dob,height,wikidata_id FROM players WHERE tour=? AND player_id=?', key,
                    ).fetchone()
                player = player_cache[key]
                if not player:
                    continue
                hand, roster_dob, roster_height, _qid = player
                fallback = wikidata.get(key, {})
                dob = parse_dob(roster_dob)
                dob_source = 'Sackmann roster' if dob else None
                if not dob:
                    dob = parse_dob(fallback.get('date_of_birth_fallback'))
                    dob_source = 'Wikidata CC0' if dob else None
                if dob and date(1850, 1, 1) <= dob <= event_day:
                    age = round((event_day - dob).days / 365.2425, 1)
                    if not 12 <= age <= 70:
                        dob = None
                if dob:
                    age = round((event_day - dob).days / 365.2425, 1)
                    output[f'{side}_age_fallback'] = age
                    output[f'{side}_birth_date'] = dob.isoformat()
                    output[f'{side}_birth_date_source'] = dob_source
                    ages[side] = age
                    changed = True

                height = height_cm(roster_height)
                height_source = 'Sackmann roster profile' if height else None
                if height is None:
                    height = height_cm(fallback.get('height_cm_fallback'))
                    height_source = 'Wikidata CC0' if height else None
                if height is not None:
                    output[f'{side}_ht_fallback'] = height
                    output[f'{side}_height_source'] = height_source
                    heights[side] = height
                    changed = True

                hand_value = (hand or '').strip().upper()
                if hand_value:
                    output[f'{side}_hand_fallback'] = hand_value
                    output[f'{side}_hand_source'] = 'Sackmann roster'
                    changed = True
            if 'p1' in ages and 'p2' in ages:
                output['age_diff_fallback'] = round(ages['p1'] - ages['p2'], 1)
            if 'p1' in heights and 'p2' in heights:
                output['height_diff_fallback'] = heights['p1'] - heights['p2']
            if changed:
                appended.append(output)

    if appended:
        append_mode = OUT.exists()
        with gzip.open(OUT, 'at' if append_mode else 'wt', encoding='utf-8', newline='', compresslevel=6) as target:
            writer = csv.DictWriter(target, fieldnames=FIELDS)
            if not append_mode:
                writer.writeheader()
            writer.writerows(appended)

    rows = 0
    counts = Counter()
    tour_counts = defaultdict(Counter)
    if OUT.exists():
        with gzip.open(OUT, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                rows += 1
                tour = row['tour']
                populated = False
                for side in ('p1', 'p2'):
                    for field, name in (('age_fallback', 'age'), ('ht_fallback', 'height'), ('hand_fallback', 'hand')):
                        if row[f'{side}_{field}']:
                            counts[name] += 1
                            tour_counts[tour][name] += 1
                            populated = True
                if populated:
                    counts['rows'] += 1
                    tour_counts[tour]['rows'] += 1
    report = {
        'rows_with_profile_data': rows,
        'recent_feature_rows': recent_feature_rows,
        'field_values': dict(counts),
        'field_values_by_tour': {tour: dict(values) for tour, values in sorted(tour_counts.items())},
        'height_is_historical': False,
        'age_basis': 'Birth date plus exact Valuebetennis match date; rounded to one decimal year.',
        'profile_supplement_sha256': sha256(OUT) if OUT.exists() else None,
        'input_recent_features_sha256': sha256(FEATURES),
        'input_database_sha256': sha256(DB),
        'input_wikidata_profile_supplement_sha256': sha256(PROFILE_ENRICHMENT),
        'supplement_file': 'data/odds/recent_player_profiles.csv.gz',
        'policy': 'Append-only; join by record_id and fill only missing age/height/hand features. Birth date must be valid on the match date. Height is a roster profile value, not a historical height-at-match observation. Provenance is recorded per field.',
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'new_rows_appended': len(appended), **report}, indent=2))


if __name__ == '__main__':
    main()
