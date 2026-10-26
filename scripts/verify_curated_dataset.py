"""Check every curated result, keys, source values, dates, prices and file hashes."""
import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date, timedelta

from build_curated_dataset import ROOT, OUT, DB, ODDS, LINKS, RANKS, read_gzip, sha, odds_fields, source_manifest_sha
from curated_quality import completed_result, decimal_price, orient_score, profile_height


def require(condition, message):
    if not condition:
        raise ValueError(message)


def source_fingerprint(values):
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).digest()


def main():
    manifest = json.loads((OUT / 'manifest.json').read_text())
    require(source_manifest_sha() == manifest['archive_source_manifest_lf_sha256'], 'Changed archive source manifest')
    for relative, digest in manifest['inputs_sha256'].items():
        require(sha(ROOT / relative) == digest, 'Changed input: ' + relative)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity')
    source_fields = [r[1] for r in db.execute('PRAGMA table_info(matches)')]
    archive_expected = {}
    players = {r['player_id']: r for r in read_gzip(OUT / 'players.csv.gz')}
    for player in players.values():
        require(not player['height_cm'] or profile_height(player['height_cm']) == player['height_cm'], 'Implausible player height: ' + player['player_id'])
    invalid_source_heights = {
        f"sackmann:{r['tour']}:{r['player_id']}"
        for r in db.execute('SELECT tour,player_id,height FROM players WHERE height IS NOT NULL')
        if r['height'] and not profile_height(r['height'])
    }
    seen, recent, counts, latest = set(), {}, Counter(), {}
    links = {r['sackmann_record_id']: r for r in read_gzip(LINKS)}
    linked_provider_ids = {r['match_id'] for r in links.values()}
    fallbacks = {r['record_id']: r for r in read_gzip(RANKS)}
    cutoff = {r[0]: date.fromisoformat(r[1]) for r in db.execute('SELECT tour,max(event_date) FROM matches GROUP BY tour')}
    both_ranked, both_serve, open_pairs, exact_dates, filled_rank_values = 0, 0, 0, 0, 0
    for info in manifest['files']:
        path = OUT / info['path']
        require(sha(path) == info['sha256'] and path.stat().st_size == info['bytes'], 'File hash/size: ' + str(path))
        n = 0
        for row in read_gzip(path):
            n += 1
            if 'record_id' not in row:
                continue
            rid = row['record_id']
            require(rid not in seen, 'Duplicate result: ' + rid)
            seen.add(rid)
            require('2000-01-01' <= row['event_date'] <= manifest['as_of_date'], 'Date outside release: ' + rid)
            require(row['winner_id'] != row['loser_id'], 'Identical players: ' + rid)
            for side in ('winner', 'loser'):
                require(row[f'{side}_id'] in players, 'Missing player: ' + rid)
                require(players[row[f'{side}_id']]['tour'] == row['tour'], 'Player tour mismatch: ' + rid)
                snapshot = row[f'{side}_rank_snapshot_date']
                if snapshot:
                    d = date.fromisoformat(snapshot)
                    require(0 < (date.fromisoformat(row['event_date']) - d).days <= 90, 'Ranking timing: ' + rid)
                for stat in ('rank', 'rank_points'):
                    if row[f'{side}_{stat}_source'] == 'match_file':
                        require(row[f'{side}_{stat}_effective'] == row[f'{side}_{stat}'], 'Changed match-file ranking: ' + rid)
                    if row[f'{side}_{stat}_source'] == 'weekly_snapshot':
                        fallback = fallbacks[rid]
                        p = 'p1' if fallback['p1_id'] == row[f'source_{side}_id'] else 'p2'
                        require(row[f'{side}_{stat}_effective'] == fallback[f'{p}_{stat}_fallback'], 'Incorrect ranking fallback: ' + rid)
                        filled_rank_values += 1
            for k, v in row.items():
                if k.startswith('odds_') and k.endswith('_decimal') and v:
                    require(decimal_price(v) == v, 'Invalid decimal odds: ' + rid)
            if row['source'] == 'sackmann':
                for side in ('winner', 'loser'):
                    require(row[f'{side}_id'] == f"sackmann:{row['tour']}:{row[f'source_{side}_id']}", 'Player namespace: ' + rid)
                archive_expected[rid] = source_fingerprint([
                    row['source_' + k] if k in ('winner_id', 'loser_id') else row[k]
                    for k in source_fields
                ])
                require(row['date_precision'] == 'tournament_start', 'Date precision: ' + rid)
                if rid in links:
                    for k, v in odds_fields(links[rid]).items():
                        require(row[k] == v, 'Misaligned historical odds: ' + rid)
                    require(row['match_date'] == links[rid]['date'][:10], 'Historical match date: ' + rid)
            else:
                require(row['source'] == 'valuebetennis', 'Unknown source: ' + rid)
                require(row['source_record_id'] not in linked_provider_ids, 'Cross-source duplicate: ' + rid)
                require(date.fromisoformat(row['event_date']) > cutoff[row['tour']] + timedelta(days=14), 'Archive overlap buffer: ' + rid)
                require(row['date_precision'] == 'match_day' and row['match_date'] == row['event_date'], 'Recent date precision: ' + rid)
                recent[row['source_record_id']] = row
            counts[row['source']] += 1
            latest[row['source']] = max(latest.get(row['source'], ''), row['event_date'])
            both_ranked += bool(row['winner_rank_effective'] and row['loser_rank_effective'])
            both_serve += bool(row['w_svpt'] and row['l_svpt'])
            open_pairs += bool(row['odds_open_winner_decimal'] and row['odds_open_loser_decimal'])
            exact_dates += bool(row['match_date'])
        require(n == info['rows'], 'Row count: ' + str(path))
        print(f"Checked {info['path']}: {n:,} rows", flush=True)
    # A sequential source scan avoids 1.25 million random primary-key lookups.
    # Fingerprint every original field, not just a sample or selected columns.
    for original in db.execute("SELECT * FROM matches NOT INDEXED WHERE event_date >= '2000-01-01' AND event_date <= ?", (manifest['as_of_date'],)):
        if not original['winner_id'] or not original['loser_id'] or original['winner_id'] == original['loser_id'] or original['source_extra_cells']:
            continue
        rid = original['record_id']
        actual = source_fingerprint([str(original[k]) if original[k] is not None else '' for k in source_fields])
        require(archive_expected.pop(rid, None) == actual, 'Archive row missing or changed: ' + rid)
    require(not archive_expected, 'Curated archive IDs absent from source')
    verified_recent = set()
    with ODDS.open(encoding='utf-8', newline='') as stream:
        for raw in csv.DictReader(stream):
            row = recent.get(raw['match_id'])
            if not row:
                continue
            require(completed_result(raw) == 'completed', 'Unsettled curated result: ' + raw['match_id'])
            require(row['source_winner_id'] == raw['vainqueur_id'], 'Winner mismatch: ' + raw['match_id'])
            require(row['score'] == orient_score(raw['score'], raw['vainqueur_id'] == raw['joueur1_id']), 'Score orientation')
            require(row['event_date'] == raw['date'][:10], 'Recent source date')
            for k, v in odds_fields(raw).items():
                require(row[k] == v, 'Recent odds orientation: ' + raw['match_id'])
            verified_recent.add(raw['match_id'])
    require(verified_recent == recent.keys(), 'Missing recent source rows')
    require(len(seen) == manifest['match_rows'] and dict(counts) == manifest['matches_by_source'], 'Total/source count')
    require(len(players) == manifest['player_rows'], 'Player count')
    require(latest == manifest['latest_dates_by_source'], 'Latest source dates')
    issues = Counter()
    for row in read_gzip(OUT / 'issues.csv.gz'):
        issues[row['source'] + ':' + row['reason']] += 1
    require(dict(issues) == manifest['excluded_rows_by_reason'], 'Exclusion ledger counts')
    archive_exclusions = sum(n for k, n in issues.items() if k.startswith('sackmann:'))
    provider_exclusions = sum(n for k, n in issues.items() if k.startswith('valuebetennis:'))
    require(counts['sackmann'] + archive_exclusions == manifest['source_row_accounting']['sackmann'], 'Archive row accounting')
    require(counts['valuebetennis'] + provider_exclusions == manifest['source_row_accounting']['valuebetennis_unlinked'], 'Provider row accounting')
    result = dict(passed=True, match_rows=len(seen), player_rows=len(players),
        matches_by_source=dict(counts), latest_dates_by_source=latest,
        both_players_ranked=both_ranked, both_serve_counts_present=both_serve,
        paired_opening_odds=open_pairs, exact_match_dates=exact_dates,
        ranking_values_filled=filled_rank_values,
        issue_ledger_rows=sum(issues.values()),
        profile_height_rows_checked=len(players),
        implausible_source_profile_heights_omitted=sum(pid in players and not players[pid]['height_cm'] for pid in invalid_source_heights),
        scope='Every exported row checked against local source values; IDs, date precision, rank timing, odds orientation, file hashes and counts. Does not prove source accuracy or exhaustive real-world coverage.')
    (OUT / 'validation_report.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
