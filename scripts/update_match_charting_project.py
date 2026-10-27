"""Append licensed Match Charting Project match metadata and aggregate stats."""
import csv
import difflib
import gzip
import hashlib
import io
import json
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/curated/match_charting'
MANIFEST = OUT / 'manifest.json'
LINKS = OUT / 'match_links.csv.gz'
LINK_CORRECTIONS = OUT / 'match_link_corrections.csv.gz'
SOURCE_CORRECTIONS = OUT / 'source_corrections.csv.gz'
REPO_API = 'https://api.github.com/repos/JeffSackmann/tennis_MatchChartingProject'
USER_AGENT = 'tennis-history-data-source-audit/1.0 (personal research dataset)'
ROUND_CODES = {'F', 'SF', 'QF', 'R16', 'R32', 'R64', 'R128', 'R256', 'RR',
               'Q1', 'Q2', 'Q3', 'Q4', 'R1', 'R2', 'R3', 'R4', 'BRZ', '3P'}


def request_bytes(url, attempts=4):
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT,
                                                       'Accept': 'application/vnd.github+json'})
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt + 1 == attempts:
                raise
            time.sleep(2 ** attempt)


def api_json(url):
    return json.loads(request_bytes(url).decode('utf-8'))


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def normalize_name(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(c for c in value if not unicodedata.combining(c)).lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value).split())


def parse_date(value):
    value = (value or '').strip()
    if re.fullmatch(r'\d{8}', value):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def title_score(left, right):
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    ignore = {'atp', 'wta', 'masters', 'master', 'open', 'tennis', 'the', 'international',
              'championship', 'championships', 'tour', 'grand', 'slam', 'cup'}
    ta, tb = set(a.split()) - ignore, set(b.split()) - ignore
    overlap = len(ta & tb) / max(1, len(ta | tb))
    return max(overlap, difflib.SequenceMatcher(None, a, b).ratio() * 0.55)


def source_key(tour, fields, row):
    names = set(fields)
    if 'match_id' not in names:
        raise ValueError('Source file has no match_id field')
    if {'server', 'returner', 'row'} <= names:
        return (row['match_id'], row['server'], row['returner'], row['row'])
    if 'Pt' in names:
        return (row['match_id'], row['Pt'])
    if 'player' in names and 'row' in names:
        return (row['match_id'], row['player'], row['row'])
    if {'player', 'set'} <= names:
        return (row['match_id'], row['player'], row['set'])
    return (row['match_id'],)


def row_digest(row, fields):
    payload = '\x1f'.join(row.get(field, '') or '' for field in fields)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def usable_source_row(row, kind):
    if not row.get('match_id') or None in row:
        return False
    if kind == 'matches':
        if not row.get('Player 1') or not row.get('Player 2') or not row.get('Tournament'):
            return False
        if not parse_date(row.get('Date')):
            return False
        surface = normalize_name(row.get('Surface'))
        if surface and surface not in {'hard', 'clay', 'grass', 'carpet'}:
            return False
    return True


def recover_match_metadata(row, tour):
    """Recover key fields from a charting match ID when a CSV row is shifted."""
    if usable_source_row(row, 'matches'):
        return row, False
    parts = (row.get('match_id') or '').split('-')
    if len(parts) < 6 or not re.fullmatch(r'\d{8}', parts[0]):
        return row, False
    expected_tour = {'M': 'atp', 'W': 'wta'}.get(parts[1])
    round_code = parts[-3]
    if expected_tour != tour or round_code not in ROUND_CODES:
        return row, False
    tournament_parts = parts[2:-3]
    player_1, player_2 = parts[-2], parts[-1]
    if not tournament_parts or not player_1 or not player_2:
        return row, False
    recovered = dict(row)
    recovered['Date'] = parts[0]
    recovered['Tournament'] = ' '.join(' '.join(tournament_parts).replace('_', ' ').split())
    recovered['Round'] = round_code
    recovered['Player 1'] = player_1.replace('_', ' ')
    recovered['Player 2'] = player_2.replace('_', ' ')
    if recovered.get('Pl 1 hand') not in {'R', 'L'}:
        recovered['Pl 1 hand'] = ''
    if recovered.get('Pl 2 hand') not in {'R', 'L'}:
        recovered['Pl 2 hand'] = ''
    if recovered.get('Surface') not in {'Hard', 'Clay', 'Grass', 'Carpet'}:
        recovered['Surface'] = ''
    if recovered.get('Best of') not in {'3', '5'}:
        recovered['Best of'] = ''
    recovered['Time'] = ''
    recovered['Court'] = ''
    recovered['Umpire'] = ''
    recovered['Charted by'] = ''
    return recovered, True


def existing_records(path, fields, tour):
    records = {}
    if not path.exists():
        return records
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != fields:
            raise ValueError(f'Published schema changed in {path}; refusing to rewrite it.')
        for row in reader:
            key = source_key(tour, fields, row)
            if key in records:
                raise ValueError(f'Duplicate key {key!r} in published charting source {path}')
            records[key] = row_digest(row, fields)
    return records


def append_csv_gzip(path, fields, rows, header_needed):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 'wt' if header_needed else 'at'
    with gzip.open(path, mode, encoding='utf-8', newline='', compresslevel=9) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
        if header_needed:
            writer.writeheader()
        writer.writerows(rows)


def source_targets(tree):
    targets = []
    for item in tree:
        name = item['path'].rsplit('/', 1)[-1]
        if not item['path'].startswith('charting-') or not name.endswith('.csv'):
            continue
        match = re.fullmatch(r'charting-([mw])-(matches|stats-.+)\.csv', name)
        if not match:
            continue
        gender, kind = match.groups()
        tour = 'atp' if gender == 'm' else 'wta'
        if kind == 'matches':
            relative = f'matches/{tour}_matches.csv.gz'
        else:
            category = kind.removeprefix('stats-')
            relative = f'stats/{tour}_{category}.csv.gz'
        targets.append((item, relative, tour))
    return targets


def load_chart_metadata(paths):
    rows = []
    for tour, path in paths:
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                item = dict(row)
                item['_tour'] = tour
                rows.append(item)
    return rows


def link_new_chart_matches(chart_rows, already_linked):
    pair_keys = set()
    for row in chart_rows:
        if row['match_id'] in already_linked:
            continue
        when = parse_date(row.get('Date'))
        a, b = normalize_name(row.get('Player 1')), normalize_name(row.get('Player 2'))
        if when and a and b:
            pair_keys.add((row['_tour'], when.year, tuple(sorted((a, b)))))

    index = defaultdict(list)
    for path in sorted((ROOT / 'data/curated/post_2000/matches').glob('*.csv.gz')):
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                tour = row.get('tour', '').lower()
                if tour not in {'atp', 'wta'}:
                    continue
                a, b = normalize_name(row.get('winner_name')), normalize_name(row.get('loser_name'))
                if not a or not b:
                    continue
                key = (tour, int((row.get('event_date') or '0000')[:4]), tuple(sorted((a, b))))
                if key not in pair_keys:
                    continue
                link_date = parse_date(row.get('match_date')) or parse_date(row.get('event_date'))
                if not link_date:
                    continue
                index[key].append({
                    'record_id': row['record_id'], 'event_date': row.get('event_date', ''),
                    'match_date': row.get('match_date', ''), 'tourney_id': row.get('tourney_id', ''),
                    'tourney_name': row.get('tourney_name', ''), 'surface': row.get('surface', ''),
                    'date': link_date,
                })

    output = []
    for row in chart_rows:
        if row['match_id'] in already_linked:
            continue
        when = parse_date(row.get('Date'))
        a, b = normalize_name(row.get('Player 1')), normalize_name(row.get('Player 2'))
        candidates = []
        if when and a and b:
            key = (row['_tour'], when.year, tuple(sorted((a, b))))
            for candidate in index.get(key, []):
                gap = abs((when - candidate['date']).days)
                if gap > 14:
                    continue
                source_surface = normalize_name(row.get('Surface'))
                archive_surface = normalize_name(candidate.get('surface'))
                if source_surface and archive_surface and source_surface != archive_surface:
                    continue
                candidates.append((gap, title_score(row.get('Tournament'), candidate.get('tourney_name')), candidate))
        status, selected = 'unmatched_no_unique_pair_date_candidate', None
        if candidates:
            candidates.sort(key=lambda x: (x[0], -x[1]))
            best = candidates[0]
            tied = [item for item in candidates if item[:2] == best[:2]]
            if len(tied) == 1:
                status, selected = 'unique_pair_nearest_date_candidate', best[2]
            else:
                status = 'ambiguous_candidate_tie'
        output.append({
            'chart_match_id': row['match_id'], 'tour': row['_tour'],
            'chart_date': row.get('Date', ''), 'chart_tournament': row.get('Tournament', ''),
            'chart_round': row.get('Round', ''), 'chart_surface': row.get('Surface', ''),
            'player_1': row.get('Player 1', ''), 'player_2': row.get('Player 2', ''),
            'record_id': selected['record_id'] if selected else '',
            'archive_event_date': selected['event_date'] if selected else '',
            'archive_match_date': selected['match_date'] if selected else '',
            'archive_tourney_id': selected['tourney_id'] if selected else '',
            'archive_tourney_name': selected['tourney_name'] if selected else '',
            'archive_surface': selected['surface'] if selected else '',
            'date_gap_days': str(abs((when - selected['date']).days)) if selected else '',
            'candidate_count_within_14_days': str(len(candidates)),
            'link_status': status,
        })
    return output


def current_link_metrics():
    base = {}
    for path in (LINKS, LINK_CORRECTIONS):
        if not path.exists():
            continue
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                base[row['chart_match_id']] = row
    return {
        'base_link_rows': sum(1 for _ in _iter_csv_gzip(LINKS)) if LINKS.exists() else 0,
        'unique_chart_match_ids': len(base),
        'effective_link_status_counts': dict(sorted(Counter(r['link_status'] for r in base.values()).items())),
        'effective_archive_link_count': sum(bool(r.get('record_id')) for r in base.values()),
        'link_method_limit': 'Unique player/date candidate links are not official IDs or score-verified links; preserve unresolved statuses.',
    }


def _iter_csv_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    repo = api_json(REPO_API)
    branch = repo['default_branch']
    commit = api_json(f'{REPO_API}/commits/{branch}')
    revision = commit['sha']
    old_manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    if (old_manifest.get('source_revision') == revision
            and old_manifest.get('processing_schema_version') == 3
            and LINKS.exists()):
        print(json.dumps({'source_revision': revision, 'status': 'already_current',
                          'detail': 'No upstream Match Charting Project change detected; tracked data left untouched.'}))
        return

    with tempfile.TemporaryDirectory(prefix='mcp-source-', dir=ROOT / 'data/processed') as temp_name:
        temp = Path(temp_name)
        tree_doc = api_json(f'{REPO_API}/git/trees/{revision}?recursive=1')
        targets = source_targets(tree_doc['tree'])
        if not any(relative.endswith('_matches.csv.gz') for _, relative, _ in targets):
            raise ValueError('No match metadata files found in the source tree.')

        asset_reports = {}
        newly_linkable = []
        current_metadata_rows = []
        metadata_correction_ids = set()
        source_correction_records = []
        match_paths = []
        source_headers = {}
        for item, relative, tour in targets:
            source_path = item['path']
            raw = request_bytes(f'https://raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/{revision}/{source_path}')
            source_file = temp / Path(source_path).name
            source_file.write_bytes(raw)
            with source_file.open('r', encoding='utf-8-sig', newline='') as stream:
                reader = csv.DictReader(stream)
                fields = reader.fieldnames
                if not fields:
                    raise ValueError(f'Empty CSV header in {source_path}')
                source_headers[relative] = fields
                rows = list(reader)
            raw_source_row_count = len(rows)
            kind = 'matches' if relative.startswith('matches/') else 'stats'
            malformed_recovered = 0
            malformed = []
            normalized_rows = []
            for row in rows:
                if kind == 'matches':
                    row, recovered = recover_match_metadata(row, tour)
                    malformed_recovered += int(recovered)
                if usable_source_row(row, kind):
                    normalized_rows.append(row)
                else:
                    malformed.append(row)
            rows = normalized_rows
            # Some upstream CSVs repeat a match/player/row key after a correction.
            # Resolve duplicates within the current source snapshot to its last row.
            staged = {}
            duplicate_keys = 0
            for row in rows:
                key = source_key(tour, fields, row)
                if key in staged:
                    duplicate_keys += 1
                staged[key] = row
            rows = list(staged.values())
            out_path = OUT / relative
            old = existing_records(out_path, fields, tour)
            additions, conflicts = [], []
            conflict_rows = []
            for row in rows:
                key = source_key(tour, fields, row)
                current_hash = row_digest(row, fields)
                previous_hash = old.get(key)
                if previous_hash is None:
                    old[key] = current_hash
                    additions.append(row)
                elif previous_hash != current_hash:
                    conflicts.append('|'.join(key))
                    conflict_rows.append((key, row))
            append_csv_gzip(out_path, fields, additions, not out_path.exists())
            report = {
                'source_path': source_path,
                'output_path': out_path.relative_to(ROOT).as_posix(),
                'schema': fields,
                'source_rows': raw_source_row_count,
                'usable_source_rows': len(rows),
                'malformed_rows_recovered_from_match_id': malformed_recovered,
                'malformed_rows_skipped': len(malformed),
                'duplicate_source_keys_collapsed': duplicate_keys,
                'published_rows_after_append': len(old),
                'new_rows_appended': len(additions),
                'changed_existing_keys_ignored': len(conflicts),
                'changed_key_samples': conflicts[:10],
                'source_sha256': sha256_bytes(raw),
                'output_sha256': sha256_file(out_path),
            }
            asset_reports[relative] = report
            if relative.endswith('_matches.csv.gz'):
                match_paths.append((tour, out_path))
                for row in rows:
                    row['_tour'] = tour
                    current_metadata_rows.append(row)
                metadata_correction_ids.update(key[0] for key, _ in conflict_rows)
            for key, row in conflict_rows:
                source_correction_records.append({
                    'source_file': source_path,
                    'source_key': json.dumps(list(key), ensure_ascii=False, separators=(',', ':')),
                    'source_revision': revision,
                    'record_json': json.dumps({field: row.get(field, '') or '' for field in fields},
                                              ensure_ascii=False, separators=(',', ':')),
                    'record_sha256': row_digest(row, fields),
                })

        # Save the source's own data dictionary and license notice alongside the derived exports.
        upstream_readme = request_bytes(f'https://raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/{revision}/README.md')
        dictionary = request_bytes(f'https://raw.githubusercontent.com/JeffSackmann/tennis_MatchChartingProject/{revision}/data_dictionary.txt')
        (OUT / 'UPSTREAM_README.md').write_bytes(upstream_readme)
        (OUT / 'data_dictionary.txt').write_bytes(dictionary)

        existing_linked = set()
        if LINKS.exists():
            with gzip.open(LINKS, 'rt', encoding='utf-8', newline='') as stream:
                existing_linked = {row['chart_match_id'] for row in csv.DictReader(stream)}
        newly_linkable = [row for row in current_metadata_rows if row['match_id'] not in existing_linked]
        link_rows = link_new_chart_matches(newly_linkable, existing_linked)
        link_fields = [
            'chart_match_id', 'tour', 'chart_date', 'chart_tournament', 'chart_round', 'chart_surface',
            'player_1', 'player_2', 'record_id', 'archive_event_date', 'archive_match_date',
            'archive_tourney_id', 'archive_tourney_name', 'archive_surface', 'date_gap_days',
            'candidate_count_within_14_days', 'link_status',
        ]
        append_csv_gzip(LINKS, link_fields, link_rows, not LINKS.exists())
        linked_counts = Counter(row['link_status'] for row in link_rows)

        # Keep source edits visible as append-only correction overlays instead of
        # replacing any earlier published observations.
        existing_corrections = set()
        if SOURCE_CORRECTIONS.exists():
            with gzip.open(SOURCE_CORRECTIONS, 'rt', encoding='utf-8', newline='') as stream:
                existing_corrections = {(r['source_file'], r['source_key'], r['record_sha256'])
                                         for r in csv.DictReader(stream)}
        new_corrections = [r for r in source_correction_records
                           if (r['source_file'], r['source_key'], r['record_sha256']) not in existing_corrections]
        correction_fields = ['source_file', 'source_key', 'source_revision', 'record_json', 'record_sha256']
        append_csv_gzip(SOURCE_CORRECTIONS, correction_fields, new_corrections,
                        not SOURCE_CORRECTIONS.exists())

        corrected_metadata = [r for r in current_metadata_rows
                              if r['match_id'] in metadata_correction_ids]
        corrected_link_rows = link_new_chart_matches(corrected_metadata, set())
        for row in corrected_link_rows:
            row['source_revision'] = revision
        link_correction_fields = link_fields + ['source_revision']
        append_csv_gzip(LINK_CORRECTIONS, link_correction_fields, corrected_link_rows,
                        not LINK_CORRECTIONS.exists())

    report = {
        'source': 'Tennis Abstract Match Charting Project',
        'source_url': 'https://github.com/JeffSackmann/tennis_MatchChartingProject',
        'source_license': 'CC BY-NC-SA 4.0',
        'attribution': 'Crowdsourced shot-by-shot professional tennis data by The Tennis Abstract Match Charting Project; https://github.com/JeffSackmann/tennis_MatchChartingProject',
        'source_revision': revision,
        'processing_schema_version': 3,
        'source_default_branch': branch,
        'refreshed_at_utc': datetime.now(timezone.utc).isoformat(),
        'append_policy': 'Published source rows are immutable. New source keys are appended; changed values for existing keys are retained in the original publication and recorded in the append-only source-correction overlay.',
        'coverage_note': 'Contributor-charted subset of professional matches, not an exhaustive tour census. Statistics are post-match observations and must not be used directly as pre-match predictors.',
        'assets': asset_reports,
        'match_link_file': LINKS.relative_to(ROOT).as_posix(),
        'new_match_links_added': len(link_rows),
        'new_match_link_status_counts': dict(sorted(linked_counts.items())),
        'effective_match_link_coverage': current_link_metrics(),
        'source_corrections_overlay': SOURCE_CORRECTIONS.relative_to(ROOT).as_posix(),
        'source_correction_rows_appended': len(new_corrections),
        'match_link_corrections_overlay': LINK_CORRECTIONS.relative_to(ROOT).as_posix(),
        'match_link_correction_rows_appended': len(corrected_link_rows),
        'match_link_method': 'Same tour, unordered normalized player-name pair, same calendar year, source date within 14 days of archive exact match date or event date, surface agreement when both are known; a unique nearest candidate is required. This is a candidate crosswalk, not an official ID match.',
    }
    MANIFEST.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({
        'source_revision': revision,
        'source_csv_files': len(asset_reports),
        'source_match_metadata_rows': sum(v['source_rows'] for k, v in asset_reports.items() if k.startswith('matches/')),
        'new_match_links_added': len(link_rows),
        'new_match_link_status_counts': dict(sorted(linked_counts.items())),
        'stats_rows_appended': sum(v['new_rows_appended'] for k, v in asset_reports.items() if k.startswith('stats/')),
        'changed_existing_source_keys_ignored': sum(v['changed_existing_keys_ignored'] for v in asset_reports.values()),
        'source_correction_rows_appended': len(new_corrections),
        'match_link_correction_rows_appended': len(corrected_link_rows),
    }, indent=2))


if __name__ == '__main__':
    main()
