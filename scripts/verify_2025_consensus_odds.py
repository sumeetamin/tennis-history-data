"""Verify every published 2025 consensus link and its model-player orientation."""
import csv
import gzip
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/odds'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rows(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def index(items, field):
    result = {row[field]: row for row in items}
    require(len(result) == len(items) and '' not in result, f'Blank/duplicate {field}')
    return result


def normalize(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value).casefold() if c.isascii() and c.isalnum())


def name_matches(short, full):
    surname, initial = short.rsplit(' ', 1)
    parts = full.split()
    return (normalize(initial) == normalize(parts[0])[:1]
            and normalize(surname) in {normalize(' '.join(parts[start:])) for start in range(1, len(parts))})


def sets(value):
    return [(int(a), int(b)) for a, b in re.findall(r'(\d+)\s*[-–]\s*(\d+)', value)]


def close(a, b):
    return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)


def flags(row):
    result = []
    for side in (1, 2):
        try:
            value = float(row[f'best_close_odds{side}'])
            if not math.isfinite(value) or value <= 1:
                result.append(f'source_p{side}_invalid_best_close')
            elif value / float(row[f'close_fair_odds{side}']) > 2:
                result.append(f'source_p{side}_best_close_above_twice_fair')
        except (KeyError, ValueError):
            result.append(f'source_p{side}_missing_best_close')
    return ';'.join(result)


def main():
    report = json.loads((BASE / 'multi_bookmaker_consensus_2025_report.json').read_text())
    source_path = ROOT / report['source']['raw_file']
    require(sha256(source_path) == report['source']['raw_sha256'], 'Source checksum mismatch')
    require(sha256(ROOT / report['source']['source_card_file']) == report['source']['source_card_sha256'], 'Source card checksum mismatch')
    source = index(rows(source_path), 'match_id')
    require(len(source) == report['source']['raw_rows'], 'Source row count mismatch')
    outputs = {}
    for key in ('output', 'model_feature_output'):
        details = report[key]
        path = ROOT / details['path']
        require(sha256(path) == details['sha256'], f'{key} checksum mismatch')
        require(path.stat().st_size == details['bytes'], f'{key} byte size mismatch')
        outputs[key] = rows(path)
    links = index(outputs['output'], 'record_id')
    index(outputs['output'], 'source_match_id')
    models = index(outputs['model_feature_output'], 'record_id')
    require(len(links) == report['counts']['linked_rows'], 'Link count mismatch')
    require(len(models) == report['model_feature_output']['rows'] == report['counts']['linked_with_model_feature'], 'Model count mismatch')
    features = {}
    for name, expected_hash in report['inputs']['feature_files'].items():
        path = ROOT / name
        require(sha256(path) == expected_hash, 'Historical feature checksum mismatch')
        features.update(index(rows(path), 'record_id'))
    database = ROOT / 'data/processed/tennis.sqlite'
    # SQLite's binary serialization can change across runtime versions even
    # when its logical contents are equivalent. Validate integrity and every
    # referenced archive row below instead of comparing the database file hash.
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as integrity_db:
        require(integrity_db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Archive integrity check failed')
    aliases = defaultdict(set)
    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        for key, link in links.items():
            raw = source[link['source_match_id']]
            match = db.execute('SELECT * FROM matches WHERE record_id=?', (key,)).fetchone()
            require(match is not None, f'Missing archive record {key}')
            for target, original in [('event_date', 'event_date'), ('archive_winner_id', 'winner_id'),
                                     ('archive_loser_id', 'loser_id'), ('archive_score', 'score'),
                                     ('archive_outcome', 'outcome'), ('archive_tournament', 'tourney_name')]:
                require(link[target] == match[original], f'Archive field mismatch {key}: {target}')
            require(link['tour'] == match['tour'] == raw['tour'].lower(), f'Tour mismatch {key}')
            gap = (date.fromisoformat(match['event_date']) - date.fromisoformat(raw['date_utc'])).days
            require(abs(gap) <= 14 and int(link['event_start_gap_days']) == gap, f'Date gap mismatch {key}')
            require(link['match_date_utc'] == raw['date_utc'], f'Match date mismatch {key}')
            require(link['source_status'] == raw['status'] and link['source_score'] == raw['score'], f'Status/score mismatch {key}')
            ids = [link['source_player1_archive_id'], link['source_player2_archive_id']]
            require(set(ids) == {match['winner_id'], match['loser_id']}, f'Player-ID mapping mismatch {key}')
            for side in (1, 2):
                role = 'winner' if ids[side - 1] == match['winner_id'] else 'loser'
                require(name_matches(raw[f'player{side}'], match[f'{role}_name']), f'Name mapping mismatch {key}')
                require(link[f'source_player{side}_id'] == raw[f'player{side}_id'], f'Source player-ID mismatch {key}')
                aliases[(link['tour'], raw[f'player{side}_id'])].add(ids[side - 1])
            require(raw['winner'] in ('1', '2') and ids[int(raw['winner']) - 1] == match['winner_id'], f'Winner mismatch {key}')
            expected_score = sets(match['score'])
            if ids[0] != match['winner_id']:
                expected_score = [(b, a) for a, b in expected_score]
            require(sets(raw['score']) == expected_score and expected_score, f'Set-score mismatch {key}')
            require(link['best_close_quality_flags'] == flags(raw), f'Quality flags mismatch {key}')
            for period in ('open', 'close'):
                require(link[f'{period}_prob_p1'] == raw[f'{period}_prob1'], f'Source probability changed {key}')
                for side in (1, 2):
                    require(link[f'{period}_fair_odds_p{side}'] == raw[f'{period}_fair_odds{side}'], f'Source fair odds changed {key}')
            for side in (1, 2):
                require(link[f'best_close_odds_p{side}'] == raw[f'best_close_odds{side}'], f'Raw best price changed {key}')
    require(all(len(values) == 1 for values in aliases.values()), 'Conflicting source-player alias')

    for key, row in models.items():
        link = links[key]
        raw = source[row['odds_2025_source_match_id']]
        original = features[key]
        require(row['odds_2025_source_match_id'] == link['source_match_id'], f'Wrong market joined {key}')
        require(all(row[col] == value for col, value in original.items()), f'Historical features altered {key}')
        require(raw['status'] == 'finished' and link['archive_outcome'] == 'completed', f'Noncompleted model row {key}')
        require({row['p1_id'], row['p2_id']} == {link['source_player1_archive_id'], link['source_player2_archive_id']}, f'Wrong model players {key}')
        flip = row['p1_id'] != link['source_player1_archive_id']
        for period in ('open', 'close'):
            probability = float(raw[f'{period}_prob1'])
            require(close(row[f'odds_2025_{period}_prob_p1'], 1 - probability if flip else probability), f'Probability orientation {key}')
            for model_side in (1, 2):
                source_side = 3 - model_side if flip else model_side
                require(row[f'odds_2025_{period}_fair_odds_p{model_side}'] == raw[f'{period}_fair_odds{source_side}'], f'Fair-odds orientation {key}')
        expected_flags = flags(raw)
        require(row['odds_2025_best_close_quality_flags'] == expected_flags, f'Model flags mismatch {key}')
        require(row['odds_2025_best_close_pair_available'] == str(int(not expected_flags)), f'Availability flag mismatch {key}')
        for side in (1, 2):
            source_side = 3 - side if flip else side
            expected = '' if expected_flags else raw[f'best_close_odds{source_side}']
            require(row[f'odds_2025_best_close_odds_p{side}'] == expected, f'Best-price filter/orientation {key}')
        require(close(row['odds_2025_prob_move_pts'], float(raw['prob_move_pts']) * (-1 if flip else 1)), f'Line-movement orientation {key}')

    require(set(models) == {key for key, link in links.items() if key in features and link['source_status'] == 'finished' and link['archive_outcome'] == 'completed'}, 'Model subset incomplete')
    result = {'validated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'source_rows': len(source), 'archive_links_checked': len(links), 'model_rows_checked': len(models),
              'source_player_aliases_checked': len(aliases),
              'model_rows_by_tour': dict(Counter(row['tour'] for row in models.values())),
              'model_rows_with_best_close_pair_blanked': sum(bool(row['odds_2025_best_close_quality_flags']) for row in models.values()),
              'report_sha256': sha256(BASE / 'multi_bookmaker_consensus_2025_report.json'),
              'scope': 'Full source/archive links, unique IDs and aliases, result agreement, unchanged historical features, ID-based market orientation, best-price filtering, file hashes. Source quote timing is not independently verified.',
              'passed': True}
    (BASE / 'consensus_2025_validation_report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
