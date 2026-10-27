"""Publish append-only, player-oriented Valuebetennis odds quote records."""
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/odds/atp_wta_match_odds.csv'
LINKS = ROOT / 'data/odds/linked_odds_sackmann.csv.gz'
MATCH_DIR = ROOT / 'data/curated/post_2000/matches'
OUT_DIR = ROOT / 'data/odds/quotes/by_year'
LEGACY_OUT = ROOT / 'data/odds/quotes/odds_quotes_long.csv.gz'
CORRECTIONS = ROOT / 'data/odds/quotes/odds_quote_corrections.csv.gz'
MANIFEST = ROOT / 'data/odds/quotes/manifest.json'
FIELDS = [
    'quote_id', 'source', 'source_license', 'source_match_id', 'source_row_number', 'record_id',
    'tour', 'source_event_id', 'canonical_event_id', 'event_name', 'match_date',
    'source_match_date_raw', 'player_source_id', 'canonical_player_id', 'player_name',
    'opponent_source_id', 'market', 'market_outcome', 'bookmaker', 'odds_stage',
    'source_stage_label', 'decimal_odds', 'source_price_raw', 'price_status',
    'quote_timestamp_utc', 'quote_timestamp_status', 'match_start_time_local',
    'match_start_time_utc', 'match_timezone', 'result_available_at_utc',
    'timing_basis', 'link_status',
]
CORRECTION_FIELDS = ['quote_id', 'corrected_at_utc', 'old_row_sha256', 'new_row_sha256', 'new_row_json']
SOURCE_URL = 'https://www.valuebetennis.com/donnees.htm'
LICENSE = 'CC BY 4.0'


def read_gzip(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def digest(row):
    data = json.dumps([row.get(name, '') or '' for name in FIELDS], ensure_ascii=False,
                      separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote_year(row):
    year = (row.get('match_date') or '')[:4]
    return year if year.isdigit() else 'unknown'


def year_path(year):
    return OUT_DIR / f'odds_quotes_{year}.csv.gz'


def migrate_legacy_export():
    """Partition an earlier local monolith into uploadable season files."""
    if not LEGACY_OUT.exists() or any(OUT_DIR.glob('odds_quotes_*.csv.gz')):
        return None
    buffers = {}
    stats = {'rows': 0, 'source_match_rows': 0, 'tour_counts': Counter(),
             'stage_counts': Counter(), 'match_dates': [], 'source_rows_seen': set()}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for row in read_gzip(LEGACY_OUT):
        year = quote_year(row)
        stats['rows'] += 1
        stats['tour_counts'][row.get('tour') or 'unknown'] += 1
        stats['stage_counts'][(row.get('tour', ''), row.get('odds_stage', ''), row.get('price_status', ''))] += 1
        if row.get('odds_stage') == 'opening' and row.get('source_row_number') not in stats['source_rows_seen']:
            stats['source_rows_seen'].add(row.get('source_row_number'))
            stats['source_match_rows'] += 1
            if len(row.get('match_date', '')) == 10:
                stats['match_dates'].append(row['match_date'])
        buffers.setdefault(year, []).append(row)
        if len(buffers[year]) >= 20000:
            append_gzip(year_path(year), FIELDS, buffers[year])
            buffers[year].clear()
    for year, rows in buffers.items():
        append_gzip(year_path(year), FIELDS, rows)
    return stats


def partition_manifest(yearly_counts):
    return {
        path.relative_to(ROOT).as_posix(): {
            'rows': yearly_counts[path.stem.removeprefix('odds_quotes_')],
            'bytes': path.stat().st_size, 'sha256': file_sha(path),
        }
        for path in sorted(OUT_DIR.glob('odds_quotes_*.csv.gz'))
    }


def partition_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def normalized(value):
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', (value or '').casefold()).split())


def decimal(value):
    text = (value or '').strip().replace(',', '.')
    if not text:
        return '', 'missing'
    try:
        number = Decimal(text)
    except InvalidOperation:
        return '', 'invalid'
    if not number.is_finite() or number <= 1:
        return '', 'invalid'
    return format(number.normalize(), 'f'), 'valid'


def make_quote_id(match_id, source_row_number, stage, player_source_id, side):
    key = '|'.join(('Valuebetennis', match_id, str(source_row_number), 'match_winner', stage,
                    str(side), player_source_id or ''))
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def timing_fields():
    return {
        'quote_timestamp_utc': '', 'quote_timestamp_status': 'not_provided_by_source',
        'match_start_time_local': '', 'match_start_time_utc': '', 'match_timezone': '',
        'result_available_at_utc': '',
        'timing_basis': 'Provider supplies a match-date string and opening/last-pre-match labels but no verifiable quote timestamp or time zone; do not treat date time as quote or start time.',
    }


def load_archive_map():
    link_candidates = {}
    if LINKS.exists():
        for row in read_gzip(LINKS):
            if row.get('sackmann_record_id'):
                link_candidates.setdefault(row['match_id'], []).append(row)
    link_map = {match_id: (rows[0] if len(rows) == 1 else {'link_method': 'ambiguous_duplicate_source_match_id'})
                for match_id, rows in link_candidates.items()}
    records_by_year = {}
    needed = {}
    for row in link_map.values():
        tour = (row.get('genre') or '').casefold()
        year = (row.get('sackmann_event_date') or '')[:4]
        if tour in {'atp', 'wta'} and year.isdigit():
            needed.setdefault((tour, year), set()).add(row['sackmann_record_id'])
    for (tour, year), ids in needed.items():
        path = MATCH_DIR / f'{tour}_{year}.csv.gz'
        if not path.exists():
            continue
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                if row.get('record_id') in ids:
                    records_by_year[row['record_id']] = row
    record_map = records_by_year
    return record_map, link_map


def build_rows():
    record_map, link_map = load_archive_map()
    seen = set()
    with SOURCE.open('r', encoding='utf-8-sig', newline='') as stream:
        for source_row_number, match in enumerate(csv.DictReader(stream), start=2):
            match_id = (match.get('match_id') or '').strip()
            if not match_id:
                continue
            link = link_map.get(match_id, {})
            archive = record_map.get(link.get('sackmann_record_id', ''), {})
            tour = (match.get('genre') or '').casefold()
            event_id = match.get('tournoi_id', '')
            for stage, label, price_fields in (
                ('opening', 'ouverture', ('cote1_ouverture', 'cote2_ouverture')),
                ('last_pre_match', 'cloture', ('cote1_cloture', 'cote2_cloture')),
            ):
                for side, price_field, player_field, player_id_field, opponent_field, opponent_id_field in (
                    (1, price_fields[0], 'joueur1', 'joueur1_id', 'joueur2', 'joueur2_id'),
                    (2, price_fields[1], 'joueur2', 'joueur2_id', 'joueur1', 'joueur1_id'),
                ):
                    player_name = match.get(player_field, '') or ''
                    player_source_id = match.get(player_id_field, '') or ''
                    quote_id = make_quote_id(match_id, source_row_number, stage, player_source_id, side)
                    if quote_id in seen:
                        raise ValueError(f'Duplicate quote key in source: {match_id}/{stage}/{side}')
                    seen.add(quote_id)
                    price, price_status = decimal(match.get(price_field, ''))
                    canonical_player = ''
                    if archive and normalized(player_name) in {
                        normalized(archive.get('winner_name')), normalized(archive.get('loser_name')),
                    }:
                        canonical_player = archive['winner_id'] if normalized(player_name) == normalized(archive.get('winner_name')) else archive['loser_id']
                    row = {
                        'quote_id': quote_id, 'source': 'Valuebetennis', 'source_license': LICENSE,
                        'source_match_id': match_id, 'source_row_number': str(source_row_number),
                        'record_id': link.get('sackmann_record_id', ''),
                        'tour': tour, 'source_event_id': event_id,
                        'canonical_event_id': archive.get('tourney_id', ''),
                        'event_name': match.get('tournoi', ''),
                        'match_date': (match.get('date') or '')[:10],
                        'source_match_date_raw': match.get('date', '') or '',
                        'player_source_id': player_source_id, 'canonical_player_id': canonical_player,
                        'player_name': player_name, 'opponent_source_id': match.get(opponent_id_field, '') or '',
                        'market': 'match_winner', 'market_outcome': 'player_win', 'bookmaker': 'Pinnacle',
                        'odds_stage': stage, 'source_stage_label': label,
                        'decimal_odds': price, 'source_price_raw': match.get(price_field, '') or '',
                        'price_status': price_status,
                        **timing_fields(),
                        'link_status': link.get('link_method', 'unlinked'),
                    }
                    yield row


def append_gzip(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = 'at' if path.exists() else 'wt'
    with gzip.open(path, mode, encoding='utf-8', newline='', compresslevel=9) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n', extrasaction='ignore')
        if mode == 'wt':
            writer.writeheader()
        writer.writerows(rows)


def main():
    if not SOURCE.exists():
        raise SystemExit(f'Missing odds source: {SOURCE}')
    prior_manifest = json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else {}
    migrated = migrate_legacy_export()
    source_sha = file_sha(SOURCE)
    if migrated is None and prior_manifest.get('schema_version') == 3 and prior_manifest.get('source_sha256') == source_sha:
        actual_paths = {path.relative_to(ROOT).as_posix() for path in OUT_DIR.glob('odds_quotes_*.csv.gz')}
        manifest_paths = set(prior_manifest.get('files', {}))
        files_unchanged = True
        for rel_path, info in prior_manifest.get('files', {}).items():
            path = ROOT / rel_path
            if not path.exists() or path.stat().st_size != info['bytes'] or file_sha(path) != info['sha256']:
                files_unchanged = False
                break
        if (files_unchanged and manifest_paths == actual_paths and prior_manifest.get('files')
                and prior_manifest.get('sha256') == partition_digest(prior_manifest['files'])):
            print(json.dumps({'status': 'already_current', 'quotes': prior_manifest.get('rows', 0),
                              'files': prior_manifest['files']}, indent=2))
            return
    if migrated is not None and prior_manifest.get('source_sha256') == source_sha and migrated['rows'] == prior_manifest.get('rows'):
        yearly_counts = Counter({path.stem.removeprefix('odds_quotes_'): sum(1 for _ in read_gzip(path))
                                 for path in OUT_DIR.glob('odds_quotes_*.csv.gz')})
        files = partition_manifest(yearly_counts)
        manifest = dict(prior_manifest)
        manifest.update({
            'dataset': OUT_DIR.relative_to(ROOT).as_posix(), 'schema_version': 3,
            'files': files, 'source_match_rows': migrated['source_match_rows'],
            'source_match_date_range': [min(migrated['match_dates']), max(migrated['match_dates'])] if migrated['match_dates'] else [],
            'quote_rows_by_tour': dict(sorted(migrated['tour_counts'].items())),
            'stage_counts': {f'{tour}:{stage}:{status}': count for (tour, stage, status), count in sorted(migrated['stage_counts'].items())},
            'new_quotes_appended': 0, 'quote_corrections_appended': 0,
            'sha256': partition_digest(files), 'refreshed_at_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        })
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(json.dumps({'status': 'partitioned_legacy_export', 'quotes': migrated['rows'],
                          'files': files}, indent=2))
        return
    existing_hashes = {}
    yearly_counts = Counter()
    for path in sorted(OUT_DIR.glob('odds_quotes_*.csv.gz')):
        year = path.stem.removeprefix('odds_quotes_')
        for row in read_gzip(path):
            existing_hashes[row['quote_id']] = digest(row)
            yearly_counts[year] += 1
    latest_hashes = {}
    if CORRECTIONS.exists():
        for row in read_gzip(CORRECTIONS):
            latest_hashes[row['quote_id']] = row['new_row_sha256']
    effective_hashes = dict(existing_hashes)
    effective_hashes.update(latest_hashes)
    seen_corrections = {(row['quote_id'], row['new_row_sha256']) for row in read_gzip(CORRECTIONS)} if CORRECTIONS.exists() else set()
    additions, corrections = [], []
    additions_count = correction_count = 0
    counts = Counter()
    source_match_rows = 0
    tour_counts = Counter()
    match_dates = []
    source_rows_seen = set()
    refreshed = datetime.now(timezone.utc).isoformat(timespec='seconds')

    def flush():
        nonlocal additions_count, correction_count
        if additions:
            grouped = {}
            for item in additions:
                grouped.setdefault(quote_year(item), []).append(item)
            for year, rows in grouped.items():
                append_gzip(year_path(year), FIELDS, rows)
                yearly_counts[year] += len(rows)
            additions_count += len(additions)
            additions.clear()
        if corrections:
            fresh = [item for item in corrections if (item['quote_id'], item['new_row_sha256']) not in seen_corrections]
            append_gzip(CORRECTIONS, CORRECTION_FIELDS, fresh)
            correction_count += len(fresh)
            seen_corrections.update((item['quote_id'], item['new_row_sha256']) for item in fresh)
            corrections.clear()

    for row in build_rows():
        key = row['quote_id']
        counts[(row['tour'], row['odds_stage'], row['price_status'])] += 1
        tour_counts[row['tour'] or 'unknown'] += 1
        if row['odds_stage'] == 'opening' and row['source_row_number'] not in source_rows_seen:
            source_rows_seen.add(row['source_row_number'])
            source_match_rows += 1
            if len(row['match_date']) == 10:
                match_dates.append(row['match_date'])
        current_hash = digest(row)
        previous_hash = effective_hashes.get(key)
        if previous_hash is None:
            additions.append(row)
            effective_hashes[key] = current_hash
        elif previous_hash != current_hash:
            corrections.append({
                'quote_id': key, 'corrected_at_utc': refreshed,
                'old_row_sha256': previous_hash, 'new_row_sha256': current_hash,
                'new_row_json': json.dumps(row, ensure_ascii=False, separators=(',', ':')),
            })
            effective_hashes[key] = current_hash
        if len(additions) + len(corrections) >= 20000:
            flush()
    flush()
    files = partition_manifest(yearly_counts)
    output_sha = partition_digest(files)
    if (not additions_count and not correction_count and
            prior_manifest.get('schema_version') == 3 and
            prior_manifest.get('source_sha256') == source_sha and
            prior_manifest.get('sha256') == output_sha):
        print(json.dumps({'status': 'already_current', 'quotes': len(effective_hashes),
                          'new_quotes': 0, 'quote_corrections': 0}, indent=2))
        return
    manifest = {
        'dataset': OUT_DIR.relative_to(ROOT).as_posix(), 'schema_version': 3,
        'source': 'Valuebetennis historical tennis results and odds since 2021',
        'source_url': SOURCE_URL, 'source_license': LICENSE,
        'source_sha256': source_sha, 'rows': len(effective_hashes),
        'source_match_rows': source_match_rows,
        'source_match_date_range': [min(match_dates), max(match_dates)] if match_dates else [],
        'quote_rows_by_tour': dict(sorted(tour_counts.items())),
        'files': files,
        'new_quotes_appended': additions_count, 'quote_corrections_appended': correction_count,
        'stage_counts': {f'{tour}:{stage}:{status}': count for (tour, stage, status), count in sorted(counts.items())},
        'market': 'Match winner, decimal price, one row per source player and quoted stage.',
        'bookmaker': 'Pinnacle as attributed by Valuebetennis.',
        'timestamp_policy': 'No individual quote timestamp, verified match start time, time zone, or result-publication time is supplied. Those columns are intentionally blank; opening/last-pre-match stages are provider labels, not timestamp proof.',
        'identity_policy': 'Provider match/player/event IDs and original CSV row numbers are retained; quote IDs include source row number because provider match IDs may be duplicated. Canonical player/event IDs are filled only when the strict archive match crosswalk identifies the match and exact player name.',
        'append_policy': 'New quote IDs append. If the source changes an existing quote value, the original row remains immutable and the latest value is recorded in the correction overlay.',
        'corrections_path': CORRECTIONS.relative_to(ROOT).as_posix(),
        'refreshed_at_utc': refreshed,
        'sha256': output_sha,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'quotes': len(effective_hashes), 'new_quotes': additions_count,
                      'quote_corrections': correction_count, 'coverage': manifest['stage_counts']}, indent=2))


if __name__ == '__main__':
    main()
