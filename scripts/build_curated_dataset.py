"""Publish append-only, provenance-bearing post-2000 singles CSVs. No imputation."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import sqlite3
import tempfile
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from build_recent_odds_features import norm, surface
from curated_quality import completed_result, decimal_price, orient_score, profile_height

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/curated/post_2000'
DB = ROOT / 'data/processed/tennis.sqlite'
ODDS = ROOT / 'data/odds/atp_wta_match_odds.csv'
LINKS = ROOT / 'data/odds/linked_odds_sackmann.csv.gz'
RANKS = ROOT / 'data/processed/supplements/ranking_fallbacks.csv.gz'
PROFILES = ROOT / 'data/processed/supplements/player_profile_enrichment.csv.gz'
EXTRA = ['source', 'source_record_id', 'date_precision', 'match_date',
         'source_winner_id', 'source_loser_id', 'winner_identity_status', 'loser_identity_status',
         'score_validation', 'quality_flags', 'odds_provider_match_id', 'odds_date',
         'odds_open_winner_decimal', 'odds_open_loser_decimal',
         'odds_close_winner_decimal', 'odds_close_loser_decimal']
for SIDE in ('winner', 'loser'):
    EXTRA += [f'{SIDE}_rank_effective', f'{SIDE}_rank_points_effective',
              f'{SIDE}_rank_source', f'{SIDE}_rank_points_source', f'{SIDE}_rank_snapshot_date']
PLAYER_FIELDS = ['player_id', 'tour', 'source', 'source_player_id', 'name', 'name_first',
                 'name_last', 'hand', 'dob', 'ioc', 'height_cm', 'wikidata_id',
                 'dob_source', 'height_source', 'identity_status']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_manifest_sha():
    # Git checks this JSON out with LF; Windows rebuilds may use CRLF.
    data = (ROOT / 'data/source_files.json').read_bytes().replace(b'\r\n', b'\n')
    return hashlib.sha256(data).hexdigest()


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def normalized(row, fields):
    return {k: '' if row.get(k) is None else str(row.get(k, '')) for k in fields}


def fingerprint(row, fields):
    return hashlib.sha256(json.dumps([row[k] for k in fields], ensure_ascii=False).encode()).digest()


class AppendTable:
    """Stage new gzip members; reject changes to any already-published record."""
    def __init__(self, path, fields, key, scratch, stack):
        self.path, self.fields, self.key = path, fields, key
        self.existing, self.seen, self.count = {}, set(), 0
        if path.exists():
            for row in read_gzip(path):
                if list(row) != fields or row[key] in self.existing:
                    raise ValueError(f'Invalid existing schema/key: {path}')
                self.existing[row[key]] = fingerprint(row, fields)
        self.original_sha = sha(path) if path.exists() else None
        self.stage = scratch / (path.name + '.pending')
        raw = stack.enter_context(self.stage.open('wb'))
        compressed = stack.enter_context(gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0))
        text = stack.enter_context(io.TextIOWrapper(compressed, encoding='utf-8', newline=''))
        self.writer = csv.DictWriter(text, fieldnames=fields, lineterminator='\n')
        if not path.exists():
            self.writer.writeheader()

    def add(self, row):
        row = normalized(row, self.fields)
        key = row[self.key]
        if not key or key in self.seen:
            raise ValueError(f'Duplicate/empty key {key}: {self.path}')
        self.seen.add(key)
        if key in self.existing:
            if self.existing[key] != fingerprint(row, self.fields):
                raise ValueError(f'Existing row changed: {self.path} {key}; use a correction overlay')
        else:
            self.writer.writerow(row)
            self.count += 1

    def check(self):
        if self.existing.keys() - self.seen:
            raise ValueError(f'Previously published rows absent from rebuild: {self.path}')
        if self.path.exists() and sha(self.path) != self.original_sha:
            raise ValueError(f'Concurrent modification: {self.path}')

    def publish(self):
        if self.count or not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('ab') as target, self.stage.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    target.write(block)


def odds_fields(row):
    winner = '1' if row['vainqueur_id'] == row['joueur1_id'] else '2'
    loser = '2' if winner == '1' else '1'
    out = dict(odds_provider_match_id=row['match_id'], odds_date=row['date'][:10])
    for side, number in (('winner', winner), ('loser', loser)):
        for label, source in (('open', 'ouverture'), ('close', 'cloture')):
            out[f'odds_{label}_{side}_decimal'] = decimal_price(row.get(f'cote{number}_{source}'))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    args = parser.parse_args()
    if args.as_of < date(2000, 1, 1):
        parser.error('--as-of must be on or after 2000-01-01')
    OUT.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('Archive integrity failure')
    print('Archive integrity verified; resolving existing source links', flush=True)
    base_fields = [r[1] for r in db.execute('PRAGMA table_info(matches)')]
    fields = base_fields + EXTRA
    links = {r['sackmann_record_id']: r for r in read_gzip(LINKS)}
    linked_ids = {r['match_id'] for r in links.values()}
    aliases, names = defaultdict(set), defaultdict(set)
    for row in db.execute('SELECT record_id,tour,winner_id,loser_id FROM matches'):
        link = links.get(row['record_id'])
        if not link:
            continue
        w, l = ('1', '2') if link['vainqueur_id'] == link['joueur1_id'] else ('2', '1')
        for side, n in (('winner', w), ('loser', l)):
            key = row['tour'], link[f'joueur{n}_id']
            aliases[key].add(row[f'{side}_id'])
            names[key].add(norm(link[f'joueur{n}']))
    ranks = {r['record_id']: r for r in read_gzip(RANKS)}
    enrichment = {(r['tour'], r['player_id']): r for r in read_gzip(PROFILES)}
    roster = {(r['tour'], r['player_id']): dict(r) for r in db.execute('SELECT * FROM players')}
    cutoff = {r[0]: date.fromisoformat(r[1]) for r in db.execute('SELECT tour,max(event_date) FROM matches GROUP BY tour')}
    used_players, tables, metrics = {}, {}, defaultdict(Counter)
    issue_counts, flags_count = Counter(), Counter()
    included_sources, identities = Counter(), Counter()
    latest = {}
    source_counts = Counter()
    inputs = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p) for p in (ODDS, LINKS, RANKS, PROFILES)}
    archive_manifest = source_manifest_sha()
    print('Source links and supplements loaded; preparing release', flush=True)

    def archive_player(tour, pid):
        key = f'sackmann:{tour}:{pid}'
        if key not in used_players:
            raw = roster.get((tour, pid), {})
            enrich = enrichment.get((tour, pid), {})
            dob = raw.get('dob') or enrich.get('date_of_birth_fallback', '').replace('-', '')
            height = profile_height(raw.get('height')) or profile_height(enrich.get('height_cm_fallback'))
            used_players[key] = dict(player_id=key, tour=tour, source='sackmann', source_player_id=pid,
                name=' '.join(x for x in (raw.get('name_first'), raw.get('name_last')) if x),
                name_first=raw.get('name_first'), name_last=raw.get('name_last'), hand=raw.get('hand'),
                dob=dob, ioc=raw.get('ioc'), height_cm=height, wikidata_id=raw.get('wikidata_id'),
                dob_source=('sackmann' if raw.get('dob') else 'wikidata') if dob else '',
                height_source=('sackmann' if profile_height(raw.get('height')) else 'wikidata') if height else '',
                identity_status='archive_id' if raw else 'archive_id_missing_roster')
        return key

    def provider_player(row, n):
        tour, pid, name = row['genre'], row[f'joueur{n}_id'], row[f'joueur{n}']
        key = tour, pid
        if len(aliases[key]) == 1 and norm(name) in names[key]:
            return archive_player(tour, next(iter(aliases[key]))), 'crosswalk_verified'
        canonical = f'valuebetennis:{tour}:{pid}'
        status = 'ambiguous_archive_mapping' if len(aliases[key]) > 1 else 'provider_only'
        if canonical not in used_players:
            used_players[canonical] = dict(player_id=canonical, tour=tour, source='valuebetennis',
                source_player_id=pid, name=name, identity_status=status)
        return canonical, status

    with tempfile.TemporaryDirectory(prefix='curated-', dir=ROOT / 'data/processed') as temp:
        scratch = Path(temp)
        with ExitStack() as stack:
            issues_path = scratch / 'issues.csv.gz'
            issues_raw = stack.enter_context(issues_path.open('wb'))
            issues_gzip = stack.enter_context(gzip.GzipFile(filename='', mode='wb', fileobj=issues_raw, mtime=0))
            issues_text = stack.enter_context(io.TextIOWrapper(issues_gzip, encoding='utf-8', newline=''))
            issues = csv.writer(issues_text, lineterminator='\n')
            issues.writerow(['source', 'source_record_id', 'date', 'reason'])

            def issue(source, rid, day, reason):
                issue_counts[source + ':' + reason] += 1
                issues.writerow([source, rid, day, reason])

            def emit(row):
                key = row['tour'], row['event_date'][:4]
                if key not in tables:
                    tables[key] = AppendTable(OUT / 'matches' / f'{key[0]}_{key[1]}.csv.gz', fields, 'record_id', scratch, stack)
                tables[key].add(row)
                counts = metrics[(row['tour'], row['category'], row['event_date'][:4], row['source'])]
                counts['matches'] += 1
                for field in ('surface', 'minutes', 'winner_rank_effective', 'loser_rank_effective', 'w_svpt', 'l_svpt', 'odds_open_winner_decimal', 'odds_close_winner_decimal'):
                    counts[field + '_present'] += bool(row.get(field))
                included_sources[row['source']] += 1
                latest[row['source']] = max(latest.get(row['source'], ''), row['event_date'])
                for side in ('winner', 'loser'):
                    identities[row[f'{side}_identity_status']] += 1
                flags_count.update(filter(None, row.get('quality_flags', '').split(';')))

            for index, raw in enumerate(db.execute("SELECT * FROM matches WHERE event_date >= '2000-01-01' AND event_date <= ? ORDER BY event_date,record_id", (args.as_of.isoformat(),)), 1):
                row = dict(raw)
                source_counts['sackmann'] += 1
                rid, tour = row['record_id'], row['tour']
                if not row.get('winner_id') or not row.get('loser_id') or row['winner_id'] == row['loser_id'] or row.get('source_extra_cells'):
                    issue('sackmann', rid, row['event_date'], 'invalid_identity_or_extra_cells')
                    continue
                row.update(source='sackmann', source_record_id=rid, date_precision='tournament_start',
                           score_validation='source_reported', quality_flags='')
                flags = []
                if row['outcome'] != 'completed':
                    flags.append('not_ordinary_completed_match')
                for side in ('winner', 'loser'):
                    pid = row[f'{side}_id']
                    row[f'source_{side}_id'] = pid
                    row[f'{side}_id'] = archive_player(tour, pid)
                    row[f'{side}_identity_status'] = 'archive_id'
                    fallback = ranks.get(rid, {})
                    orientation = 'p1' if fallback.get('p1_id') == pid else 'p2'
                    for stat in ('rank', 'rank_points'):
                        original = row.get(f'{side}_{stat}')
                        replacement = fallback.get(f'{orientation}_{stat}_fallback', '')
                        valid_original = bool(original) and (stat == 'rank_points' or float(original) > 0)
                        row[f'{side}_{stat}_effective'] = original if valid_original else replacement
                        row[f'{side}_{stat}_source'] = 'match_file' if valid_original else ('weekly_snapshot' if replacement else '')
                        if not valid_original and replacement:
                            row[f'{side}_rank_snapshot_date'] = fallback[f'{orientation}_rank_snapshot_date']
                link = links.get(rid)
                if link:
                    row.update(odds_fields(link))
                    row['match_date'] = link['date'][:10]
                if not row.get('surface'):
                    flags.append('missing_surface')
                row['quality_flags'] = ';'.join(flags)
                emit(row)
                if index % 250000 == 0:
                    print(f'Curated {index:,} archive results', flush=True)

            with ODDS.open(encoding='utf-8', newline='') as source:
                seen = set()
                for line, raw in enumerate(csv.DictReader(source), 2):
                    mid = raw['match_id']
                    if mid in seen:
                        raise ValueError('Duplicate provider ID: ' + mid)
                    seen.add(mid)
                    if mid in linked_ids:
                        source_counts['valuebetennis_already_linked'] += 1
                        continue
                    source_counts['valuebetennis_unlinked'] += 1
                    day, tour = raw['date'][:10], raw['genre']
                    try:
                        parsed = date.fromisoformat(day)
                    except ValueError:
                        issue('valuebetennis', mid, day, 'invalid_date')
                        continue
                    if parsed > args.as_of or parsed < date(2000, 1, 1) or tour not in cutoff:
                        issue('valuebetennis', mid, day, 'outside_release_scope')
                        continue
                    status = completed_result(raw)
                    if status != 'completed':
                        issue('valuebetennis', mid, day, status)
                        continue
                    if parsed <= cutoff[tour] + timedelta(days=14):
                        issue('valuebetennis', mid, day, 'unlinked_within_archive_window')
                        continue
                    w, l = ('1', '2') if raw['vainqueur_id'] == raw['joueur1_id'] else ('2', '1')
                    winner, wstatus = provider_player(raw, w)
                    loser, lstatus = provider_player(raw, l)
                    if winner == loser:
                        issue('valuebetennis', mid, day, 'same_resolved_player')
                        continue
                    row = dict(record_id='vb:' + mid, tour=tour, category=raw['categorie'],
                        source='valuebetennis', source_record_id=mid,
                        source_file='data/odds/atp_wta_match_odds.csv', source_row=line,
                        event_date=day, match_date=day, date_precision='match_day', outcome='completed',
                        tourney_id='valuebetennis:' + raw['tournoi_id'], tourney_name=raw['tournoi'],
                        surface=surface(raw['surface']), winner_id=winner, loser_id=loser,
                        source_winner_id=raw[f'joueur{w}_id'], source_loser_id=raw[f'joueur{l}_id'],
                        winner_identity_status=wstatus, loser_identity_status=lstatus,
                        winner_name=raw[f'joueur{w}'], loser_name=raw[f'joueur{l}'],
                        score=orient_score(raw['score'], w == '1'), score_validation='score_and_winner_checked',
                        minutes=raw['duree_min'], quality_flags='missing_detailed_match_statistics')
                    if wstatus != 'crosswalk_verified' or lstatus != 'crosswalk_verified':
                        row['quality_flags'] += ';unresolved_archive_identity'
                    row.update(odds_fields(raw))
                    emit(row)

            players = AppendTable(OUT / 'players.csv.gz', PLAYER_FIELDS, 'player_id', scratch, stack)
            for key in sorted(used_players):
                players.add(used_players[key])
        all_tables = list(tables.values()) + [players]
        for table in all_tables:
            table.check()
        # All inputs and existing rows must remain stable before publication.
        for relative, digest in inputs.items():
            if sha(ROOT / relative) != digest:
                raise ValueError('Input changed during build: ' + relative)
        if source_manifest_sha() != archive_manifest:
            raise ValueError('Archive source manifest changed during build')
        for table in all_tables:
            table.publish()
        (OUT / 'issues.csv.gz').write_bytes(issues_path.read_bytes())

    with (OUT / 'coverage.csv').open('w', encoding='utf-8', newline='') as target:
        columns = ['tour', 'category', 'year', 'source'] + sorted({k for c in metrics.values() for k in c})
        writer = csv.DictWriter(target, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        for key, counts in sorted(metrics.items()):
            writer.writerow(dict(zip(columns[:4], key)) | counts)
    manifest = dict(schema_version=1, as_of_date=args.as_of.isoformat(),
        match_rows=sum(included_sources.values()), player_rows=len(used_players),
        matches_by_source=dict(included_sources), latest_dates_by_source=latest,
        player_appearances_by_identity_status=dict(identities), quality_flags=dict(flags_count),
        source_row_accounting=dict(source_counts), excluded_rows_by_reason=dict(issue_counts),
        inputs_sha256=inputs,
        archive_source_manifest_lf_sha256=archive_manifest,
        files=[dict(path=str(t.path.relative_to(OUT)).replace('\\', '/'), rows=len(t.seen),
                    bytes=t.path.stat().st_size, sha256=sha(t.path)) for t in all_tables],
        scope='Post-2000 available singles results; not an exhaustive census. Archive dates are tournament starts. Recent results require a complete supported score, agreeing winner, and a 14-day archive-end buffer. Missing values are not imputed.',
        append_policy='Existing match and player rows are immutable. Changed source interpretations fail the rebuild and require a documented correction overlay.',
        license='Combined derivative: CC BY-NC-SA 4.0; also credit Valuebetennis CC BY 4.0 and Wikidata CC0.')
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: manifest[k] for k in ('match_rows', 'player_rows', 'matches_by_source', 'latest_dates_by_source', 'excluded_rows_by_reason')}, indent=2))
    print('New match rows appended:', sum(t.count for t in tables.values()))


if __name__ == '__main__':
    main()
