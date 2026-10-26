"""Verify the odds-to-archive crosswalk and its model-feature derivative."""
import csv
import gzip
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from link_odds_to_sackmann import norm, score_sets  # noqa: E402
from odds_quality import settlement_status  # noqa: E402

ODDS = ROOT / 'data/odds/atp_wta_match_odds.csv'
DB = ROOT / 'data/processed/tennis.sqlite'
CROSSWALK = ROOT / 'data/odds/linked_odds_sackmann.csv.gz'
LINK_REPORT = ROOT / 'data/odds/odds_link_report.json'
FEATURES = ROOT / 'data/odds/model_features_with_odds.csv.gz'
FEATURE_REPORT = ROOT / 'data/odds/model_features_with_odds_report.json'
PRICE_FIELDS = ('cote1_ouverture', 'cote2_ouverture', 'cote1_cloture', 'cote2_cloture')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    link_report = json.loads(LINK_REPORT.read_text(encoding='utf-8'))
    feature_report = json.loads(FEATURE_REPORT.read_text(encoding='utf-8'))
    assert sha(ODDS) == link_report['inputs'][ODDS.name]['sha256']
    # SQLite's serialized bytes are runtime/version dependent. Integrity plus
    # row-by-row archive comparisons below are the meaningful validation.
    with sqlite3.connect(DB) as check_db:
        assert check_db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert sha(CROSSWALK) == link_report['outputs'][CROSSWALK.name]['sha256']
    assert sha(FEATURES) == feature_report['output']['sha256']

    with gzip.open(CROSSWALK, 'rt', encoding='utf-8', newline='') as stream:
        links = list(csv.DictReader(stream))
    link_by_id = {row['match_id']: row for row in links}
    by_archive = {row['sackmann_record_id']: row for row in links}
    if len(link_by_id) != len(links) or len(by_archive) != len(links):
        raise ValueError('Crosswalk must be one-to-one on provider and archive IDs')
    source_by_id = {}
    with ODDS.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if row.get('match_id') in link_by_id:
                source_by_id[row['match_id']] = row
    assert len(source_by_id) == len(links)

    archive = {}
    ids = list(by_archive)
    with sqlite3.connect(DB) as db:
        db.execute('CREATE TEMP TABLE verify_odds_archive_ids(record_id TEXT PRIMARY KEY)')
        db.executemany('INSERT INTO verify_odds_archive_ids VALUES (?)', ((rid,) for rid in ids))
        archive.update({row[0]: row[1:] for row in db.execute(
            '''SELECT m.record_id,m.tour,m.winner_id,m.loser_id,m.winner_name,m.loser_name,
                      m.score,m.event_date,m.tourney_name,m.outcome
               FROM matches AS m JOIN verify_odds_archive_ids AS x USING(record_id)''')})
    if len(archive) != len(links):
        raise ValueError('Crosswalk references a missing or duplicate archive match')

    methods = Counter()
    missing_scores = 0
    for link in links:
        raw = source_by_id[link['match_id']]
        match = archive[link['sackmann_record_id']]
        for field in ('genre', 'tournoi', 'date', 'joueur1_id', 'joueur2_id',
                      'joueur1', 'joueur2', 'vainqueur_id', 'score'):
            assert link[field] == raw[field], (link['match_id'], field)
        assert link['genre'] == match[0]
        assert link['sackmann_event_date'] == match[6]
        assert link['sackmann_tourney_name'] == (match[7] or '')
        assert abs(int(link['event_start_gap_days'])) <= 14
        assert link['vainqueur_id'] in {link['joueur1_id'], link['joueur2_id']}
        provider_winner_name = link['joueur1'] if link['vainqueur_id'] == link['joueur1_id'] else link['joueur2']
        assert norm(provider_winner_name) == norm(match[3])
        fallback = link['link_method'].startswith('exact tour + normalized player pair; no exact event-title candidate')
        methods['event_title_fallback' if fallback else 'exact_event'] += 1
        provider_score = score_sets(raw.get('score'))
        archive_score = score_sets(match[5])
        if provider_score:
            p1_won = link['vainqueur_id'] == link['joueur1_id']
            expected = archive_score if p1_won else tuple((b, a) for a, b in archive_score)
            assert provider_score == expected
            assert link['score_match_basis'] == 'player-1 perspective; tiebreak detail ignored'
        else:
            assert not (raw.get('score') or '').strip()
            assert not fallback
            assert match[8] == 'completed'
            assert link['score_match_basis'].startswith('provider score missing;')
            missing_scores += 1

    counts = link_report['counts']
    assert len(links) == counts['linked_archive_confirmed'] == link_report['outputs'][CROSSWALK.name]['rows']
    assert methods['event_title_fallback'] == counts['linked_event_name_fallback']
    assert missing_scores == counts['linked_provider_score_missing_archive_confirmed']

    seen_features = set()
    opening_pairs = closing_pairs = 0
    with gzip.open(FEATURES, 'rt', encoding='utf-8', newline='') as stream:
        for feature in csv.DictReader(stream):
            rid = feature['record_id']
            assert rid not in seen_features
            seen_features.add(rid)
            link = by_archive[rid]
            raw = source_by_id[link['match_id']]
            match = archive[rid]
            status = settlement_status(raw)
            if status != 'completed':
                assert status == 'missing_score' and not (raw.get('score') or '').strip()
                assert link['link_method'].startswith('exact tour + normalized event + player pair;')
                assert match[8] == 'completed'
            provider_p1_is_archive_winner = raw['vainqueur_id'] == raw['joueur1_id']
            provider_p1_id = str(match[1]) if provider_p1_is_archive_winner else str(match[2])
            provider_p2_id = str(match[2]) if provider_p1_is_archive_winner else str(match[1])
            if feature['p1_id'] == provider_p1_id:
                expected_prices = tuple(raw[field] for field in PRICE_FIELDS)
            else:
                assert feature['p1_id'] == provider_p2_id
                expected_prices = (raw['cote2_ouverture'], raw['cote1_ouverture'],
                                   raw['cote2_cloture'], raw['cote1_cloture'])
            actual_prices = (feature['odds_open_p1_decimal'], feature['odds_open_p2_decimal'],
                             feature['odds_last_pre_match_p1_decimal'], feature['odds_last_pre_match_p2_decimal'])
            assert actual_prices == expected_prices
            assert int(feature['p1_won']) == int(feature['p1_id'] == str(match[1]))
            opening_pairs += bool(expected_prices[0] and expected_prices[1])
            closing_pairs += bool(expected_prices[2] and expected_prices[3])

    assert len(seen_features) == feature_report['rows']
    assert opening_pairs == feature_report['opening_odds_pair_rows']
    assert closing_pairs == feature_report['last_pre_match_odds_pair_rows']
    result = {'passed': True, 'crosswalk_rows': len(links),
              'score_verified_links': len(links) - missing_scores,
              'blank_provider_score_archive_confirmed_links': missing_scores,
              'event_title_fallback_links': methods['event_title_fallback'],
              'model_feature_rows': len(seen_features), 'opening_price_pairs': opening_pairs,
              'last_pre_match_price_pairs': closing_pairs}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
