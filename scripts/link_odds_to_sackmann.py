"""Create a conservative crosswalk between Valuebetennis odds and Sackmann matches.

Only emit a one-to-one link when tour and normalized player names, nearest event
date, winner, and player-oriented set scores all agree. Exact normalized event
names are required for primary links; a separately labeled fallback permits a
title mismatch only when no exact-title candidate exists. Original source files
are read-only; output is a separate CSV plus an audit report.
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
    candidates_by_archive_id = defaultdict(list)
    source_fields = None
    output_fields = None
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with ODDS.open(encoding='utf-8-sig', newline='') as source:
        reader = csv.DictReader(source)
        source_fields = reader.fieldnames or []
        output_fields = source_fields + [
            'sackmann_record_id', 'sackmann_event_date', 'sackmann_tourney_date',
            'sackmann_tourney_name', 'sackmann_round', 'sackmann_score',
            'event_start_gap_days', 'link_method', 'score_match_basis',
        ]
        for odds in reader:
            counts['odds_rows'] += 1
            played = parse_date(odds.get('date'))
            p1, p2 = norm(odds.get('joueur1')), norm(odds.get('joueur2'))
            pair = tuple(sorted((p1, p2)))
            if not played or not p1 or not p2:
                counts['invalid_odds_identity_or_date'] += 1
                continue
            pair_date_candidates = [
                match for match in by_pair.get((odds.get('genre'), pair), [])
                if match['event_date']
                and abs((date.fromisoformat(match['event_date']) - played).days) <= MAX_EVENT_DATE_GAP_DAYS
            ]
            if not pair_date_candidates:
                counts['no_exact_pair_event_date_candidate'] += 1
                continue

            exact_event_candidates = [match for match in pair_date_candidates
                                      if norm(match['tourney_name']) == norm(odds.get('tournoi'))]
            candidates = exact_event_candidates
            event_name_fallback = False
            if not candidates:
                # A fallback is accepted only when winner and full oriented set score
                # agree for a unique nearest same-player-pair archive record.
                event_name_fallback = True
                compatible = []
                winner_id = str(odds.get('vainqueur_id') or '')
                p1_id, p2_id = str(odds.get('joueur1_id') or ''), str(odds.get('joueur2_id') or '')
                if winner_id == p1_id:
                    odds_winner, p1_won = p1, True
                elif winner_id == p2_id:
                    odds_winner, p1_won = p2, False
                else:
                    counts['winner_id_not_resolved'] += 1
                    continue
                odds_score = score_sets(odds.get('score'))
                for match in pair_date_candidates:
                    if odds_winner != norm(match['winner_name']):
                        continue
                    archive_score = score_sets(match['score'])
                    expected_score = archive_score if p1_won else tuple((b, a) for a, b in archive_score)
                    if odds_score and odds_score == expected_score:
                        compatible.append(match)
                if not compatible:
                    counts['event_name_fallback_no_score_winner_candidate'] += 1
                    continue
                candidates = compatible
                counts['event_name_fallback_candidates'] += 1

            gaps = [abs((date.fromisoformat(match['event_date']) - played).days) for match in candidates]
            nearest_gap = min(gaps)
            nearest = [match for match, gap in zip(candidates, gaps) if gap == nearest_gap]
            if len(nearest) != 1:
                counts['event_name_fallback_nearest_tie' if event_name_fallback else 'ambiguous_nearest_candidate'] += 1
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

            counts['score_and_winner_verified_candidates'] += 1
            gap = (date.fromisoformat(match['event_date']) - played).days
            candidates_by_archive_id[match['record_id']].append({
                'odds': dict(odds),
                'match': match,
                'gap': gap,
                'absolute_gap': abs(gap),
                'event_name_fallback': event_name_fallback,
            })

    conflict_audit = []
    with gzip.open(OUT, 'wt', encoding='utf-8', newline='', compresslevel=6) as target:
        writer = csv.DictWriter(target, fieldnames=output_fields)
        writer.writeheader()
        for record_id, linked_candidates in candidates_by_archive_id.items():
            # Preserve the existing exact-event link whenever a fallback also points
            # to this archive record. The fallback only fills otherwise-unlinked rows.
            if any(not item['event_name_fallback'] for item in linked_candidates):
                counts['event_name_fallback_excluded_for_existing_exact_link'] += sum(
                    item['event_name_fallback'] for item in linked_candidates)
                linked_candidates = [item for item in linked_candidates if not item['event_name_fallback']]
            linked_candidates.sort(key=lambda item: item['absolute_gap'])
            closest_gap = linked_candidates[0]['absolute_gap']
            closest = [item for item in linked_candidates if item['absolute_gap'] == closest_gap]
            if len(linked_candidates) > 1:
                counts['archive_records_with_multiple_odds_candidates'] += 1
            if len(closest) != 1:
                counts['archive_nearest_date_tie_groups_excluded'] += 1
                counts['odds_candidates_excluded_for_archive_collision'] += len(linked_candidates)
                conflict_audit.append({
                    'sackmann_record_id': record_id,
                    'action': 'excluded_nearest_date_tie',
                    'candidate_odds_match_ids': [item['odds']['match_id'] for item in closest],
                    'absolute_event_start_gaps_days': closest_gap,
                })
                continue
            chosen = closest[0]
            rejected = len(linked_candidates) - 1
            if rejected:
                counts['odds_candidates_excluded_for_archive_collision'] += rejected
                conflict_audit.append({
                    'sackmann_record_id': record_id,
                    'action': 'kept_unique_closest_odds_record',
                    'kept_odds_match_id': chosen['odds']['match_id'],
                    'kept_absolute_event_start_gap_days': closest_gap,
                    'excluded_odds_match_ids': [item['odds']['match_id'] for item in linked_candidates[1:]],
                })
            odds = chosen['odds']
            match = chosen['match']
            if chosen['event_name_fallback']:
                counts['linked_event_name_fallback'] += 1
                method = 'exact tour + normalized player pair; no exact event-title candidate; unique nearest date within 14 days; winner and oriented set scores agree'
            else:
                method = 'exact tour + normalized event + player pair; unique nearest event date and odds record; winner and oriented set scores agree'
            writer.writerow({
                **odds,
                'sackmann_record_id': match['record_id'],
                'sackmann_event_date': match['event_date'],
                'sackmann_tourney_date': match['tourney_date'],
                'sackmann_tourney_name': match['tourney_name'],
                'sackmann_round': match['round'],
                'sackmann_score': match['score'],
                'event_start_gap_days': chosen['gap'],
                'link_method': method,
                'score_match_basis': 'player-1 perspective; tiebreak detail ignored',
            })
            counts['linked_score_and_winner_verified'] += 1

    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'odds_source': 'Valuebetennis CC BY 4.0; attribution in data/odds/README.md',
        'match_source': 'Sackmann archive mirror; source revision and license in repository manifests/docs',
        'join_policy': {
            'max_event_start_gap_days': MAX_EVENT_DATE_GAP_DAYS,
            'primary_requires_exact_normalized_tour_event_and_player_pair': True,
            'fallback_when_event_title_differs': 'same tour and normalized player pair, no exact-title candidate, unique nearest archive date within 14 days, winner and player-oriented set scores agree',
            'requires_unique_nearest_candidate': True,
            'requires_one_to_one_archive_record_link': True,
            'duplicate_archive_candidates_resolved_by_unique_nearest_odds_date': True,
            'requires_winner_and_player_oriented_set_scores_to_agree': True,
            'tiebreak_detail_compared': False,
            'source_rows_modified': False,
        },
        'counts': dict(sorted(counts.items())),
        'archive_link_conflicts': conflict_audit,
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
            'When multiple odds IDs otherwise match one archive row, only the uniquely closest odds date is kept; equal-distance conflicts are omitted and listed in the audit.',
            'This static crosswalk must be regenerated after either input dataset changes.',
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'counts': report['counts'], 'output': report['outputs'][OUT.name]}, indent=2))


if __name__ == '__main__':
    main()
