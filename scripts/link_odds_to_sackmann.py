"""Create a conservative crosswalk between Valuebetennis odds and Sackmann matches.

Only emit a link when tour, exact normalized event/player names, nearest event
date, winner, and player-oriented set scores all agree. Original source files
are read-only; output is a separate CSV plus a compact audit report.
"""
import csv
import gzip
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ODDS = ROOT / 'data/odds/atp_wta_match_odds.csv'
DB = ROOT / 'data/processed/tennis.sqlite'
OUT = ROOT / 'data/odds/linked_odds_sackmann.csv.gz'
REPORT = ROOT / 'data/odds/odds_link_report.json'
MAX_EVENT_DATE_GAP_DAYS = 14


def norm(value):
    ascii_text = ''.join(c for c in unicodedata.normalize('NFKD', value or '') if c.isascii())
    return re.sub(r'[^a-z0-9]', '', ascii_text.lower())


def parse_date(value):
    try:
        return date.fromisoformat((value or '')[:10])
    except ValueError:
        return None


def score_sets(value):
    # Ignore tiebreak detail, but retain the order and score of every set.
    return tuple((int(a), int(b)) for a, b in re.findall(r'(\d+)\s*[-–]\s*(\d+)', value or ''))


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    if not ODDS.exists() or not DB.exists():
        raise SystemExit('Build the dataset first and ensure the odds CSV exists.')

    by_pair = defaultdict(list)
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute('''SELECT record_id,tour,tourney_name,event_date,tourney_date,
                round,winner_name,loser_name,score FROM matches'''):
            pair = tuple(sorted((norm(row['winner_name']), norm(row['loser_name']))))
            if pair[0] and pair[1]:
                by_pair[(row['tour'], pair)].append(dict(row))

    counts = Counter()
    source_fields = None
    output_fields = None
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with ODDS.open(encoding='utf-8-sig', newline='') as source, gzip.open(OUT, 'wt', encoding='utf-8', newline='', compresslevel=6) as target:
        reader = csv.DictReader(source)
        source_fields = reader.fieldnames or []
        output_fields = source_fields + [
            'sackmann_record_id', 'sackmann_event_date', 'sackmann_tourney_date',
            'sackmann_tourney_name', 'sackmann_round', 'sackmann_score',
            'event_start_gap_days', 'link_method', 'score_match_basis',
        ]
        writer = csv.DictWriter(target, fieldnames=output_fields)
        writer.writeheader()

        for odds in reader:
            counts['odds_rows'] += 1
            played = parse_date(odds.get('date'))
            p1, p2 = norm(odds.get('joueur1')), norm(odds.get('joueur2'))
            pair = tuple(sorted((p1, p2)))
            if not played or not p1 or not p2:
                counts['invalid_odds_identity_or_date'] += 1
                continue
            candidates = [
                match for match in by_pair.get((odds.get('genre'), pair), [])
                if norm(match['tourney_name']) == norm(odds.get('tournoi'))
                and match['event_date']
                and abs((date.fromisoformat(match['event_date']) - played).days) <= MAX_EVENT_DATE_GAP_DAYS
            ]
            if not candidates:
                counts['no_exact_pair_event_date_candidate'] += 1
                continue

            gaps = [abs((date.fromisoformat(match['event_date']) - played).days) for match in candidates]
            nearest_gap = min(gaps)
            nearest = [match for match, gap in zip(candidates, gaps) if gap == nearest_gap]
            if len(nearest) != 1:
                counts['ambiguous_nearest_candidate'] += 1
                continue
            match = nearest[0]

            winner_id = str(odds.get('vainqueur_id') or '')
            p1_id, p2_id = str(odds.get('joueur1_id') or ''), str(odds.get('joueur2_id') or '')
            if winner_id == p1_id:
                odds_winner, p1_won = p1, True
            elif winner_id == p2_id:
                odds_winner, p1_won = p2, False
            else:
                counts['winner_id_not_resolved'] += 1
                continue
            if odds_winner != norm(match['winner_name']):
                counts['winner_disagreement'] += 1
                continue

            odds_score = score_sets(odds.get('score'))
            archive_score = score_sets(match['score'])
            expected_score = archive_score if p1_won else tuple((b, a) for a, b in archive_score)
            if not odds_score or odds_score != expected_score:
                counts['score_disagreement_or_missing'] += 1
                continue

            counts['linked_score_and_winner_verified'] += 1
            writer.writerow({
                **odds,
                'sackmann_record_id': match['record_id'],
                'sackmann_event_date': match['event_date'],
                'sackmann_tourney_date': match['tourney_date'],
                'sackmann_tourney_name': match['tourney_name'],
                'sackmann_round': match['round'],
                'sackmann_score': match['score'],
                'event_start_gap_days': (date.fromisoformat(match['event_date']) - played).days,
                'link_method': 'exact tour + normalized event + player pair; unique nearest event date; winner and oriented set scores agree',
                'score_match_basis': 'player-1 perspective; tiebreak detail ignored',
            })

    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'odds_source': 'Valuebetennis CC BY 4.0; attribution in data/odds/README.md',
        'match_source': 'Sackmann archive mirror; source revision and license in repository manifests/docs',
        'join_policy': {
            'max_event_start_gap_days': MAX_EVENT_DATE_GAP_DAYS,
            'requires_exact_normalized_tour_event_and_player_pair': True,
            'requires_unique_nearest_candidate': True,
            'requires_winner_and_player_oriented_set_scores_to_agree': True,
            'tiebreak_detail_compared': False,
            'source_rows_modified': False,
        },
        'counts': dict(sorted(counts.items())),
        'outputs': {
            OUT.name: {'rows': counts['linked_score_and_winner_verified'], 'sha256': sha256(OUT)},
        },
        'inputs': {
            ODDS.name: {'sha256': sha256(ODDS)},
            DB.name: {'sha256': sha256(DB)},
        },
        'limitations': [
            'Unlinked odds rows are not necessarily missing matches; this archive has incomplete lower-tier coverage.',
            'Score and winner checks deliberately exclude candidate links where the two sources disagree.',
            'This static crosswalk must be regenerated after either input dataset changes.',
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'counts': report['counts'], 'output': report['outputs'][OUT.name]}, indent=2))


if __name__ == '__main__':
    main()
