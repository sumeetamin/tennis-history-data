"""Append licensed Grand Slam point-by-point match summaries and audited links."""
import csv
import gzip
import hashlib
import io
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/curated/point_by_point'
MANIFEST = OUT / 'manifest.json'
MATCHES = OUT / 'grand_slam_point_match_stats.csv.gz'
LINKS = OUT / 'archive_match_links.csv.gz'
ALIASES = OUT / 'player_aliases.csv.gz'
CORRECTIONS = OUT / 'corrections.csv.gz'
REPO = 'AngieXuAU/tennis-point-by-point-archive'
API = f'https://api.github.com/repos/{REPO}'
USER_AGENT = 'tennis-history-data-point-supplement/1.0'
SCHEMA_VERSION = 5

MATCH_FIELDS = [
    'source_match_id', 'source_tour', 'source_event_id', 'source_event_name', 'season',
    'source_round', 'source_round_for_link', 'source_round_basis', 'source_status', 'source_winner_side', 'player1_source_id',
    'player1_name', 'player1_country', 'player2_source_id', 'player2_name', 'player2_country',
    'point_rows', 'known_server_point_rows', 'known_server_point_coverage',
    'player1_serve_points', 'player1_serve_points_won', 'player1_serve_points_won_rate',
    'player1_return_points', 'player1_return_points_won', 'player1_return_points_won_rate',
    'player2_serve_points', 'player2_serve_points_won', 'player2_serve_points_won_rate',
    'player2_return_points', 'player2_return_points_won', 'player2_return_points_won_rate',
    'player1_first_serve_in', 'player1_first_serve_attempts', 'player1_first_serve_in_rate',
    'player1_first_serve_points_won', 'player1_second_serve_points', 'player1_second_serve_points_won',
    'player1_first_serve_data_available',
    'player2_first_serve_in', 'player2_first_serve_attempts', 'player2_first_serve_in_rate',
    'player2_first_serve_points_won', 'player2_second_serve_points', 'player2_second_serve_points_won',
    'player2_first_serve_data_available',
    'player1_aces', 'player1_aces_available', 'player2_aces', 'player2_aces_available',
    'player1_double_faults', 'player1_double_faults_available',
    'player2_double_faults', 'player2_double_faults_available',
    'player1_winners', 'player1_winners_available', 'player2_winners', 'player2_winners_available',
    'player1_unforced_errors', 'player1_unforced_errors_available',
    'player2_unforced_errors', 'player2_unforced_errors_available',
    'player1_forced_errors', 'player1_forced_errors_available',
    'player2_forced_errors', 'player2_forced_errors_available',
    'source_matches_path', 'source_matches_blob_sha', 'source_points_path', 'source_points_blob_sha',
]
LINK_FIELDS = [
    'source_match_id', 'source_tour', 'source_event_id', 'source_event_name', 'source_round',
    'player1_source_id', 'player1_name', 'player2_source_id', 'player2_name',
    'source_round_for_link',
    'player1_name_match_method', 'player2_name_match_method',
    'player1_canonical_id', 'player2_canonical_id',
    'record_id', 'archive_event_id', 'archive_event_date', 'archive_tournament_name',
    'archive_round', 'link_status', 'candidate_count', 'link_basis',
]
ALIAS_FIELDS = [
    'alias_key', 'tour', 'source_system', 'source_player_id', 'source_player_name',
    'canonical_player_id', 'verification_status', 'verification_method', 'supporting_match_links',
    'conflicting_canonical_ids', 'human_reviewed',
]
CORRECTION_FIELDS = ['table_name', 'record_key', 'source_revision', 'old_row_sha256', 'new_row_sha256', 'new_row_json']

EVENT_NAMES = {
    'ausopen': 'Australian Open', 'frenchopen': 'Roland Garros',
    'wimbledon': 'Wimbledon', 'usopen': 'US Open',
}
EVENT_ALIASES = {
    'ausopen': {'australian open', 'aus open'},
    'frenchopen': {'roland garros', 'french open'},
    'wimbledon': {'wimbledon'}, 'usopen': {'us open', 'united states open'},
}
ROUND_MAP = {
    'round 1': {'r128', 'r128'}, 'round 2': {'r64'}, 'round 3': {'r32'},
    'round 4': {'r16'}, 'quarters': {'qf', 'quarterfinal', 'quarterfinals'},
    'semis': {'sf', 'semifinal', 'semifinals'}, 'final': {'f', 'final'},
}
POINT_SUM_FIELDS = {
    'Aces': ('player1_aces', 'player2_aces'),
    'DoubleFault': ('player1_double_faults', 'player2_double_faults'),
    'Winner': ('player1_winners', 'player2_winners'),
    'UnfErr': ('player1_unforced_errors', 'player2_unforced_errors'),
    'ForcedError': ('player1_forced_errors', 'player2_forced_errors'),
}


def request_bytes(url, attempts=4):
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': USER_AGENT, 'Accept': 'application/vnd.github+json',
            })
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)


def api_json(url):
    return json.loads(request_bytes(url).decode('utf-8'))


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def git_blob_sha(value):
    return hashlib.sha1(b'blob ' + str(len(value)).encode() + b'\0' + value).hexdigest()


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def norm(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(char for char in value if not unicodedata.combining(char)).casefold()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value).split())


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def safe_rate(numerator, denominator):
    return f'{numerator / denominator:.8g}' if denominator else ''


def read_rows(path):
    if not path.exists():
        return
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def row_hash(row, fields):
    body = json.dumps([row.get(field, '') or '' for field in fields], ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(body).hexdigest()


def append_gzip(path, fields, rows):
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 'at' if path.exists() else 'wt'
    with gzip.open(path, mode, encoding='utf-8', newline='', compresslevel=9) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        if mode == 'wt':
            writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def source_tree():
    commit = api_json(f'{API}/commits/main')['sha']
    tree = api_json(f'{API}/git/trees/{commit}?recursive=1')['tree']
    events = defaultdict(dict)
    pattern = re.compile(r'(\d{4})-(ausopen|frenchopen|wimbledon|usopen)-(matches|points)\.csv$')
    for item in tree:
        match = pattern.fullmatch(item['path'].rsplit('/', 1)[-1])
        if not match or not item['path'].startswith('slam_pointbypoint/'):
            continue
        year, slam, kind = match.groups()
        events[(int(year), slam)][kind] = item
    complete = {key: value for key, value in events.items() if {'matches', 'points'} <= value.keys()}
    if not complete:
        raise ValueError('No paired main-draw singles point and match files found in the upstream tree.')
    return commit, complete


def fetch_pinned(item, revision):
    path = item['path']
    url = f'https://raw.githubusercontent.com/{REPO}/{revision}/{path}'
    data = request_bytes(url)
    observed = git_blob_sha(data)
    if observed != item['sha']:
        raise ValueError(f'Upstream file changed while downloading {path}: expected {item["sha"]}, got {observed}')
    return data


def event_match_rows(data, source_path):
    text = data.decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(text, newline=''))
    required = {'match_id', 'player1', 'player2', 'player1id', 'player2id', 'winner', 'round', 'event_name'}
    if not required <= set(reader.fieldnames or []):
        raise ValueError(f'Match metadata schema missing fields for {source_path}')
    return {row['match_id']: row for row in reader if row.get('match_id')}


def summarize_event(meta_rows, point_data, event_key, match_item, point_item):
    year, slam = event_key
    event_id = f'{year}-{slam}'
    event_name = EVENT_NAMES[slam]
    point_text = io.TextIOWrapper(io.BytesIO(point_data), encoding='utf-8-sig', newline='')
    reader = csv.DictReader(point_text)
    fields = set(reader.fieldnames or [])
    required = {'match_id', 'PointNumber', 'PointWinner', 'PointServer'}
    if not required <= fields:
        raise ValueError(f'Point log schema missing fields for {point_item["path"]}')
    aggregates = {}
    serve_indicator_observed = False
    field_event_signal = {suffix: f'P1{suffix}' in fields and f'P2{suffix}' in fields
                          for suffix in POINT_SUM_FIELDS}
    event_nonzero = {name: False for name in POINT_SUM_FIELDS}
    for point in reader:
        if not point.get('match_id') or int(as_float(point.get('PointNumber'))) <= 0:
            continue
        bucket = aggregates.setdefault(point['match_id'], {
            'point_rows': 0, 'known_server_point_rows': 0,
            'serve_points': [0, 0], 'serve_won': [0, 0],
            'return_points': [0, 0], 'return_won': [0, 0],
            'first_in': [0, 0], 'first_attempts': [0, 0], 'first_won': [0, 0],
            'second_points': [0, 0], 'second_won': [0, 0],
            'event_sums': {suffix: [0, 0] for suffix in POINT_SUM_FIELDS},
        })
        bucket['point_rows'] += 1
        server = int(as_float(point.get('PointServer')))
        winner = int(as_float(point.get('PointWinner')))
        if server in (1, 2):
            bucket['known_server_point_rows'] += 1
            bucket['serve_points'][server - 1] += 1
            bucket['return_points'][2 - server] += 1
            if winner in (1, 2):
                bucket['serve_won'][server - 1] += winner == server
                bucket['return_won'][2 - server] += winner != server
            indicator = int(as_float(point.get('ServeIndicator')))
            if indicator in (1, 2):
                serve_indicator_observed = True
            if indicator in (1, 2):
                bucket['first_attempts'][server - 1] += 1
                if indicator == 1:
                    bucket['first_in'][server - 1] += 1
                    if winner == server:
                        bucket['first_won'][server - 1] += 1
                elif indicator == 2:
                    bucket['second_points'][server - 1] += 1
                    if winner == server:
                        bucket['second_won'][server - 1] += 1
        for suffix, target in POINT_SUM_FIELDS.items():
            for side in (1, 2):
                source_col = f'P{side}{suffix}'
                if source_col not in fields:
                    field_event_signal[suffix] = False
                    continue
                value = as_float(point.get(source_col))
                if value:
                    event_nonzero[suffix] = True
                bucket['event_sums'][suffix][side - 1] += value

    rows = []
    for match_id, meta in sorted(meta_rows.items()):
        bucket = aggregates.get(match_id, {
            'point_rows': 0, 'known_server_point_rows': 0,
            'serve_points': [0, 0], 'serve_won': [0, 0], 'return_points': [0, 0],
            'return_won': [0, 0], 'first_in': [0, 0], 'first_attempts': [0, 0],
            'first_won': [0, 0], 'second_points': [0, 0], 'second_won': [0, 0],
            'event_sums': {suffix: [0, 0] for suffix in POINT_SUM_FIELDS},
        })
        row = {
            'source_match_id': match_id,
            'source_tour': tour_from_match_metadata(meta),
            'source_event_id': event_id, 'source_event_name': event_name, 'season': str(year),
            'source_round': meta.get('round', ''), 'source_round_for_link': '', 'source_round_basis': '',
            'source_status': meta.get('status', ''),
            'source_winner_side': meta.get('winner', ''),
            'player1_source_id': meta.get('player1id', ''), 'player1_name': meta.get('player1', ''),
            'player1_country': meta.get('nation1', ''), 'player2_source_id': meta.get('player2id', ''),
            'player2_name': meta.get('player2', ''), 'player2_country': meta.get('nation2', ''),
            'point_rows': str(bucket['point_rows']),
            'known_server_point_rows': str(bucket['known_server_point_rows']),
            'known_server_point_coverage': safe_rate(bucket['known_server_point_rows'], bucket['point_rows']),
            'source_matches_path': match_item['path'], 'source_matches_blob_sha': match_item['sha'],
            'source_points_path': point_item['path'], 'source_points_blob_sha': point_item['sha'],
        }
        normalized_row = normalize_point_match(row)
        row.update(source_tour=normalized_row['source_tour'],
                   source_round_for_link=normalized_row['source_round_for_link'],
                   source_round_basis=normalized_row['source_round_basis'])
        for side in (1, 2):
            prefix = f'player{side}_'
            i = side - 1
            row[prefix + 'serve_points'] = str(bucket['serve_points'][i])
            row[prefix + 'serve_points_won'] = str(bucket['serve_won'][i])
            row[prefix + 'serve_points_won_rate'] = safe_rate(bucket['serve_won'][i], bucket['serve_points'][i])
            row[prefix + 'return_points'] = str(bucket['return_points'][i])
            row[prefix + 'return_points_won'] = str(bucket['return_won'][i])
            row[prefix + 'return_points_won_rate'] = safe_rate(bucket['return_won'][i], bucket['return_points'][i])
            serve_data = serve_indicator_observed and bucket['first_attempts'][i] > 0
            row[prefix + 'first_serve_in'] = str(bucket['first_in'][i]) if serve_data else ''
            row[prefix + 'first_serve_attempts'] = str(bucket['first_attempts'][i]) if serve_data else ''
            row[prefix + 'first_serve_in_rate'] = safe_rate(bucket['first_in'][i], bucket['first_attempts'][i]) if serve_data else ''
            row[prefix + 'first_serve_points_won'] = str(bucket['first_won'][i]) if serve_data else ''
            row[prefix + 'second_serve_points'] = str(bucket['second_points'][i]) if serve_data else ''
            row[prefix + 'second_serve_points_won'] = str(bucket['second_won'][i]) if serve_data else ''
            row[prefix + 'first_serve_data_available'] = '1' if serve_data else '0'
            for suffix, (p1_out, p2_out) in POINT_SUM_FIELDS.items():
                out = (p1_out, p2_out)[i]
                available = field_event_signal[suffix] and event_nonzero[suffix]
                row[out] = str(int(bucket['event_sums'][suffix][i])) if available else ''
                row[out + '_available'] = '1' if available else '0'
        rows.append(row)
    return rows, len(aggregates), fields


def source_match_count(path):
    return sum(1 for _ in read_rows(path)) if path.exists() else 0


def effective_rows(base_path, correction_rows, key_field):
    rows = {row[key_field]: row for row in read_rows(base_path)} if base_path.exists() else {}
    for correction in correction_rows:
        if correction['table_name'] == base_path.name:
            rows[correction['record_key']] = json.loads(correction['new_row_json'])
    return rows


def append_table_rows(path, fields, candidates, key_field, table_name, revision, correction_rows):
    old = {row[key_field]: row for row in read_rows(path)} if path.exists() else {}
    latest_corrections = {}
    for row in correction_rows:
        if row['table_name'] == path.name:
            latest_corrections[row['record_key']] = json.loads(row['new_row_json'])
    effective = dict(old)
    effective.update(latest_corrections)
    additions, changes = [], []
    for row in candidates:
        key = row[key_field]
        if not key:
            raise ValueError(f'Blank {key_field} in {table_name}')
        previous = effective.get(key)
        if previous is None:
            additions.append(row)
            effective[key] = row
        elif row_hash(previous, fields) != row_hash(row, fields):
            changes.append({
                'table_name': path.name, 'record_key': key, 'source_revision': revision,
                'old_row_sha256': row_hash(previous, fields), 'new_row_sha256': row_hash(row, fields),
                'new_row_json': json.dumps({name: row.get(name, '') or '' for name in fields},
                                           ensure_ascii=False, separators=(',', ':')),
            })
            effective[key] = row
    append_gzip(path, fields, additions)
    existing_correction_keys = {(r['table_name'], r['record_key'], r['new_row_sha256']) for r in correction_rows}
    fresh_changes = [row for row in changes if (row['table_name'], row['record_key'], row['new_row_sha256']) not in existing_correction_keys]
    append_gzip(CORRECTIONS, CORRECTION_FIELDS, fresh_changes)
    return effective, len(additions), len(fresh_changes)


def event_alias_matches(slam, archive_name):
    normalized = norm(archive_name)
    return any(alias in normalized for alias in EVENT_ALIASES[slam])


def round_matches(source_round, archive_round):
    return round_code(source_round) == round_code(archive_round)


def round_code(value):
    s = norm(value)
    mapping = {
        'round 1': 'r128', 'round 2': 'r64', 'round 3': 'r32', 'round 4': 'r16',
        'quarters': 'qf', 'quarterfinal': 'qf', 'quarterfinals': 'qf',
        'semis': 'sf', 'semifinal': 'sf', 'semifinals': 'sf', 'final': 'f',
    }
    return mapping.get(s, s)


def tour_from_match_metadata(meta):
    ids = (meta.get('player1id') or '', meta.get('player2id') or '')
    prefixes = {'atp' if value.casefold().startswith('atp') else 'wta'
                for value in ids if value.casefold().startswith(('atp', 'wta'))}
    if len(prefixes) == 1:
        return next(iter(prefixes))
    tag = (meta.get('event_name') or '').casefold()
    if tag in {'event_ms', "men's singles", 'mens singles'}:
        return 'atp'
    if tag in {'event_ws', "women's singles", 'womens singles'}:
        return 'wta'
    suffix = (meta.get('match_id') or '').rsplit('-', 1)[-1]
    if suffix.isdigit() and suffix[0] in {'1', '2'}:
        return 'wta' if suffix[0] == '2' else 'atp'
    return 'unknown'


def round_from_match_id(match_id):
    suffix = (match_id or '').rsplit('-', 1)[-1]
    if len(suffix) < 4 or not suffix.isdigit():
        return '', 'unavailable'
    round_number = int(suffix[1])
    code = {1: 'r128', 2: 'r64', 3: 'r32', 4: 'r16', 5: 'qf', 6: 'sf', 7: 'f'}.get(round_number, '')
    return code, 'match_id_bracket_code' if code else 'unavailable'


def normalize_point_match(row):
    item = dict(row)
    item['source_tour'] = tour_from_match_metadata({
        'match_id': item.get('source_match_id', ''),
        'player1id': item.get('player1_source_id', ''),
        'player2id': item.get('player2_source_id', ''),
    })
    code = round_code(item.get('source_round', ''))
    if code in {'r128', 'r64', 'r32', 'r16', 'qf', 'sf', 'f'}:
        item['source_round_for_link'] = code
        item['source_round_basis'] = 'source_match_metadata'
    else:
        item['source_round_for_link'], item['source_round_basis'] = round_from_match_id(item.get('source_match_id'))
    return item


def link_to_archive(point_rows):
    source_years = {(row['source_tour'], row['season']) for row in point_rows}
    archive_rows = defaultdict(list)
    player_registry = defaultdict(lambda: {'exact': defaultdict(set), 'surname_initial': defaultdict(set)})
    match_dir = ROOT / 'data/curated/post_2000/matches'
    for tour, year in sorted(source_years):
        path = match_dir / f'{tour}_{year}.csv.gz'
        if not path.exists():
            continue
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                if row.get('tour') != tour or (row.get('tourney_level') or '').upper() != 'G':
                    continue
                if (row.get('event_date') or '')[:4] != year:
                    continue
                slam = next((item for item in EVENT_ALIASES
                             if event_alias_matches(item, row.get('tourney_name', ''))), None)
                if not slam:
                    continue
                row['_slam'] = slam
                row['_round_code'] = round_code(row.get('round', ''))
                for side in ('winner', 'loser'):
                    player_id = row.get(side + '_id', '')
                    name = norm(row.get(side + '_name', ''))
                    if not player_id or not name:
                        continue
                    player_registry[(tour, year, slam)]['exact'][name].add(player_id)
                    words = name.split()
                    if len(words) >= 2:
                        player_registry[(tour, year, slam)]['surname_initial'][(words[-1], words[0][0])].add(player_id)
                archive_rows[(tour, year, slam)].append(row)
    result = []
    for source in point_rows:
        tour, year = source['source_tour'], source['season']
        slam = source['source_event_id'].split('-', 1)[-1]
        registry = player_registry[(tour, year, slam)]
        resolved_ids, methods = [], []
        for name in (source['player1_name'], source['player2_name']):
            normalized = norm(name)
            exact = registry['exact'].get(normalized, set())
            if len(exact) == 1:
                resolved_ids.append(next(iter(exact)))
                methods.append('exact_full_name_within_event')
                continue
            words = normalized.split()
            aliases = registry['surname_initial'].get((words[-1], words[0][0]), set()) if len(words) >= 2 else set()
            if len(aliases) == 1:
                resolved_ids.append(next(iter(aliases)))
                methods.append('unique_surname_initial_within_event')
            else:
                resolved_ids.append('')
                methods.append('unresolved_or_ambiguous_name')
        found = []
        if all(resolved_ids) and resolved_ids[0] != resolved_ids[1]:
            wanted = tuple(sorted(resolved_ids))
            for archive in archive_rows[(tour, year, slam)]:
                if archive['_round_code'] != (source.get('source_round_for_link') or round_code(source['source_round'])):
                    continue
                archive_pair = tuple(sorted((archive.get('winner_id', ''), archive.get('loser_id', ''))))
                if archive_pair == wanted:
                    found.append(archive)
        selected = found[0] if len(found) == 1 else None
        alias_used = 'unique_surname_initial_within_event' in methods
        result.append({
            'source_match_id': source['source_match_id'], 'source_tour': tour,
            'source_event_id': source['source_event_id'], 'source_event_name': source['source_event_name'],
            'source_round': source['source_round'], 'player1_source_id': source['player1_source_id'],
            'player1_name': source['player1_name'], 'player2_source_id': source['player2_source_id'],
            'player2_name': source['player2_name'],
            'source_round_for_link': source.get('source_round_for_link', ''),
            'player1_name_match_method': methods[0], 'player2_name_match_method': methods[1],
            'player1_canonical_id': resolved_ids[0] if selected else '',
            'player2_canonical_id': resolved_ids[1] if selected else '',
            'record_id': selected.get('record_id', '') if selected else '',
            'archive_event_id': selected.get('tourney_id', '') if selected else '',
            'archive_event_date': selected.get('event_date', '') if selected else '',
            'archive_tournament_name': selected.get('tourney_name', '') if selected else '',
            'archive_round': selected.get('round', '') if selected else '',
            'link_status': ('unique_event_round_player_id_pair_with_alias' if alias_used else 'unique_exact_event_round_player_pair') if selected else (
                'ambiguous_archive_pair' if len(found) > 1 else 'unmatched_or_unresolved_player_alias'),
            'candidate_count': str(len(found)),
            'link_basis': 'Same tour, season and Slam; round and two canonical archive player IDs must match uniquely. Names resolve by exact normalized name within the event, or by a unique surname-plus-first-initial within that event. Event start date is not match date.',
        })
    return result


def aliases_from_links(link_rows):
    evidence = defaultdict(lambda: defaultdict(set))
    names = defaultdict(set)
    tours = {}
    for link in link_rows:
        if not link.get('record_id'):
            continue
        for source_id_field, name_field, canonical_field in (
            ('player1_source_id', 'player1_name', 'player1_canonical_id'),
            ('player2_source_id', 'player2_name', 'player2_canonical_id'),
        ):
            source_id = link.get(source_id_field, '')
            canonical = link.get(canonical_field, '')
            if source_id and canonical:
                key = (link['source_tour'], source_id)
                evidence[key][canonical].add(link['source_match_id'])
                names[key].add(link.get(name_field, ''))
                tours[key] = link['source_tour']
    output = []
    for key, canonical_ids in sorted(evidence.items()):
        tour, source_id = key
        ids = sorted(canonical_ids)
        canonical_id = ids[0] if len(ids) == 1 else ''
        output.append({
            'alias_key': f'{tour}:sackmann_pbp:{source_id}', 'tour': tour,
            'source_system': 'Jeff Sackmann Grand Slam point-by-point archive',
            'source_player_id': source_id, 'source_player_name': sorted(names[key])[0],
            'canonical_player_id': canonical_id,
            'verification_status': 'automatic_unique_match_context_link' if canonical_id else 'conflicting_context_candidates',
            'verification_method': 'Automatically linked through unique exact event/round/opponent crosswalks; not human-reviewed and source IDs are not assumed interchangeable.',
            'supporting_match_links': str(sum(len(values) for values in canonical_ids.values())),
            'conflicting_canonical_ids': '|'.join(ids) if len(ids) > 1 else '',
            'human_reviewed': '0',
        })
    return output


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    old_manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    revision, event_sources = source_tree()
    current_file_shas = {item['path']: item['sha'] for files in event_sources.values() for item in files.values()}
    old_file_shas = old_manifest.get('source_files', {})
    if old_manifest.get('source_revision') == revision and old_manifest.get('processing_schema_version') == SCHEMA_VERSION:
        print(json.dumps({'status': 'already_current', 'source_revision': revision, 'detail': 'No upstream point archive changes.'}))
        return

    existing_base = {row['source_match_id']: row for row in read_rows(MATCHES)} if MATCHES.exists() else {}
    existing_corrections = list(read_rows(CORRECTIONS) or [])
    existing_effective = dict(existing_base)
    for correction in existing_corrections:
        if correction['table_name'] == MATCHES.name:
            existing_effective[correction['record_key']] = json.loads(correction['new_row_json'])
    existing_event_assets = defaultdict(set)
    for row in existing_effective.values():
        existing_event_assets[row['source_event_id']].add((row['source_matches_blob_sha'], row['source_points_blob_sha']))

    changed_events = []
    for event_key, files in sorted(event_sources.items()):
        event_id = f'{event_key[0]}-{event_key[1]}'
        desired_assets = (files['matches']['sha'], files['points']['sha'])
        if desired_assets not in existing_event_assets.get(event_id, set()):
            changed_events.append((event_key, files))

    point_rows = []
    event_reports = {}
    for event_key, files in changed_events:
        match_data = fetch_pinned(files['matches'], revision)
        point_data = fetch_pinned(files['points'], revision)
        metadata = event_match_rows(match_data, files['matches']['path'])
        rows, seen_points, point_columns = summarize_event(metadata, point_data, event_key, files['matches'], files['points'])
        point_rows.extend(rows)
        event_key_name = f'{event_key[0]}-{event_key[1]}'
        event_reports[event_key_name] = {
            'season': event_key[0], 'event': EVENT_NAMES[event_key[1]],
            'matches_metadata_rows': len(metadata), 'matches_with_points': seen_points,
            'point_rows_columns': point_columns,
            'matches_path': files['matches']['path'], 'matches_blob_sha': files['matches']['sha'],
            'points_path': files['points']['path'], 'points_blob_sha': files['points']['sha'],
        }

    previous_corrections = list(read_rows(CORRECTIONS) or [])
    effective_matches, added_matches, corrected_matches = append_table_rows(
        MATCHES, MATCH_FIELDS, point_rows, 'source_match_id', 'point_match_stats', revision, previous_corrections)
    normalized_rows = [normalize_point_match(row) for row in effective_matches.values()]
    normalization_corrections = list(read_rows(CORRECTIONS) or [])
    effective_matches, _, normalization_rows_added = append_table_rows(
        MATCHES, MATCH_FIELDS, normalized_rows, 'source_match_id', 'point_match_stats_normalization',
        revision, normalization_corrections)
    corrected_matches += normalization_rows_added
    links_new = link_to_archive(list(effective_matches.values()))
    link_corrections = list(read_rows(CORRECTIONS) or [])
    effective_links, added_links, corrected_links = append_table_rows(
        LINKS, LINK_FIELDS, links_new, 'source_match_id', 'archive_links', revision, link_corrections)
    all_links = list(effective_links.values())
    alias_rows = aliases_from_links(all_links)
    alias_corrections = list(read_rows(CORRECTIONS) or [])
    effective_aliases, added_aliases, corrected_aliases = append_table_rows(
        ALIASES, ALIAS_FIELDS, alias_rows, 'alias_key', 'player_aliases', revision, alias_corrections)

    source_readme = request_bytes(f'https://raw.githubusercontent.com/{REPO}/{revision}/slam_pointbypoint/UPSTREAM_README.md')
    source_dictionary = request_bytes(f'https://raw.githubusercontent.com/{REPO}/{revision}/slam_pointbypoint/data_dictionary.txt')
    (OUT / 'UPSTREAM_README.md').write_bytes(source_readme)
    (OUT / 'data_dictionary.txt').write_bytes(source_dictionary)
    status_counts = Counter(row.get('link_status', '') for row in effective_links.values())
    report = {
        'source': 'Jeff Sackmann Grand Slam point-by-point archive mirror',
        'source_url': f'https://github.com/{REPO}',
        'original_source_url': 'https://github.com/JeffSackmann/tennis_slam_pointbypoint',
        'source_license': 'CC BY-NC-SA 4.0',
        'attribution': 'Jeff Sackmann / Tennis Abstract; point-by-point archive mirrored at https://github.com/AngieXuAU/tennis-point-by-point-archive',
        'source_revision': revision, 'processing_schema_version': SCHEMA_VERSION,
        'source_files': current_file_shas,
        'source_snapshot_scope': 'Main-draw Grand Slam singles only; source coverage 2011–2024, with event omissions documented upstream. Doubles and mixed doubles are not imported.',
        'raw_download_bytes_processed': sum(item.get('size', 0) for files in event_sources.values() for item in files.values()),
        'outputs': {
            'match_stats': {'path': MATCHES.relative_to(ROOT).as_posix(), 'rows': len(effective_matches), 'sha256': file_sha(MATCHES)},
            'archive_links': {'path': LINKS.relative_to(ROOT).as_posix(), 'rows': len(effective_links), 'sha256': file_sha(LINKS)},
            'player_aliases': {'path': ALIASES.relative_to(ROOT).as_posix(), 'rows': len(effective_aliases), 'sha256': file_sha(ALIASES)},
            'corrections': {'path': CORRECTIONS.relative_to(ROOT).as_posix(),
                            'rows': sum(1 for _ in read_rows(CORRECTIONS)) if CORRECTIONS.exists() else 0,
                            'sha256': file_sha(CORRECTIONS) if CORRECTIONS.exists() else ''},
        },
        'update_counts': {
            'events_reprocessed': len(changed_events), 'match_rows_appended': added_matches,
            'match_row_corrections_appended': corrected_matches, 'archive_links_appended': added_links,
            'archive_link_corrections_appended': corrected_links, 'player_aliases_appended': added_aliases,
            'player_alias_corrections_appended': corrected_aliases,
            'normalization_corrections_appended': normalization_rows_added,
        },
        'archive_link_coverage': {
            'status_counts': dict(sorted(status_counts.items())),
            'interpretation': 'Exact normalized player names plus source Slam event, season and mapped round; unique candidate required. Link rows retain unresolved/ambiguous cases. Source match day and exact finish time are not supplied by this source.',
        },
        'event_reports': event_reports,
        'append_policy': 'Published source rows remain immutable. New source match IDs are appended; changed summaries, crosswalks or aliases are recorded as last-write-wins correction rows in corrections.csv.gz. No missing point statistic is imputed as zero.',
        'point_stat_availability_policy': 'A point outcome rate is blank when its denominator is unavailable. Event-flag totals (aces, double faults, winners and errors) are blank when the source column is absent or the entire event column is zero-only, since zero may represent uncollected data. Availability flags distinguish blank from a measured zero.',
        'timing_policy': 'The archive provides tournament year and match-relative elapsed time, not a verified local start datetime, timezone, result-publication time or odds quote time. Those fields remain unknown and are not inferred from event dates or elapsed-time values.',
        'refreshed_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({
        'source_revision': revision, 'events_reprocessed': len(changed_events),
        'match_rows_added': added_matches, 'match_corrections': corrected_matches,
        'archive_links_added': added_links, 'archive_link_status_counts': dict(status_counts),
        'player_alias_rows_added': added_aliases, 'effective_matches': len(effective_matches),
    }, indent=2))


if __name__ == '__main__':
    main()
