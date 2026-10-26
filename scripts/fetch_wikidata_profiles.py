"""Fetch CC0 profile facts for existing Sackmann Wikidata IDs.

Only missing/invalid birth dates and heights are exported. Original roster rows
are never changed; results are keyed by tour and Sackmann player ID.
"""
import csv
import gzip
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/sackmann-archive'
OUT_DIR = ROOT / 'data/processed/supplements'
OUT = OUT_DIR / 'player_profile_enrichment.csv.gz'
STAGING = OUT_DIR / 'player_profile_enrichment.building.csv.gz'
REPORT = OUT_DIR / 'player_profile_enrichment_report.json'
API = 'https://www.wikidata.org/w/api.php'
USER_AGENT = 'tennis-history-data/1.0 (https://github.com/sumeetamin/tennis-history-data; CC0 profile enrichment)'
BATCH_SIZE = 50
REQUEST_STATS = Counter()
HEIGHT_UNITS_TO_CM = {
    'Q11573': Decimal('100'),      # metre
    'Q174728': Decimal('1'),       # centimetre
    'Q174789': Decimal('0.1'),     # millimetre
    'Q218593': Decimal('2.54'),    # inch
    'Q3710': Decimal('30.48'),     # foot
}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def valid_source_dob(value):
    if not value or not re.fullmatch(r'\d{8}', value):
        return False
    try:
        parsed = datetime.strptime(value, '%Y%m%d').date()
        return date(1850, 1, 1) <= parsed <= date.today()
    except ValueError:
        return False


def valid_source_height(value):
    try:
        return Decimal(value) >= 130 and Decimal(value) <= 230
    except (InvalidOperation, TypeError):
        return False


def claim_values(entity, prop):
    statements = entity.get('claims', {}).get(prop, [])
    usable = [statement for statement in statements
              if statement.get('rank') != 'deprecated'
              and statement.get('mainsnak', {}).get('snaktype') == 'value']
    preferred = [statement for statement in usable if statement.get('rank') == 'preferred']
    return preferred or usable


def birth_date(entity):
    values = set()
    for statement in claim_values(entity, 'P569'):
        value = statement['mainsnak']['datavalue']['value']
        if value.get('precision', 0) < 11:
            continue
        raw = value.get('time', '')
        match = re.match(r'^\+(\d{4})-(\d{2})-(\d{2})T', raw)
        if not match:
            continue
        try:
            parsed = date(*map(int, match.groups()))
        except ValueError:
            continue
        if not date(1850, 1, 1) <= parsed <= date.today():
            continue
        values.add(parsed.isoformat())
    return next(iter(values)) if len(values) == 1 else None, len(values) > 1


def height_cm(entity):
    values = set()
    for statement in claim_values(entity, 'P2048'):
        value = statement['mainsnak']['datavalue']['value']
        unit = str(value.get('unit', '')).rsplit('/', 1)[-1]
        multiplier = HEIGHT_UNITS_TO_CM.get(unit)
        if multiplier is None:
            continue
        try:
            cm = (Decimal(str(value['amount'])) * multiplier).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        except (InvalidOperation, KeyError):
            continue
        if Decimal(130) <= cm <= Decimal(230):
            values.add(str(int(cm)))
    return next(iter(values)) if len(values) == 1 else None, len(values) > 1


def fetch_batch(qids):
    params = urllib.parse.urlencode({
        'action': 'wbgetentities', 'ids': '|'.join(qids), 'props': 'info|claims',
        'format': 'json', 'formatversion': '2', 'maxlag': '30',
    })
    request = urllib.request.Request(f'{API}?{params}', headers={'User-Agent': USER_AGENT})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode('utf-8'))
            error = payload.get('error')
            if error and error.get('code') == 'maxlag':
                if attempt == 4:
                    raise RuntimeError(f"Wikidata remained over maxlag: {error.get('info', '')}")
                wait_seconds = min(30, max(2, int(float(error.get('lag', 0)) + 1)))
                REQUEST_STATS['maxlag_retries'] += 1
                time.sleep(wait_seconds)
                continue
            if error:
                raise RuntimeError(f"Wikidata API error: {error.get('code')}: {error.get('info')}")
            return payload.get('entities', {})
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            time.sleep(int(error.headers.get('Retry-After', 2 ** attempt)))
    return {}


def main():
    roster_by_qid = defaultdict(list)
    roster_hashes = {}
    for tour in ('atp', 'wta'):
        path = RAW / tour / f'{tour}_players.csv'
        if not path.is_file():
            raise SystemExit(f'Missing roster: {path.relative_to(ROOT)}')
        roster_hashes[path.relative_to(ROOT).as_posix()] = sha256(path)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            for row in csv.DictReader(stream):
                qid = (row.get('wikidata_id') or '').strip()
                if not re.fullmatch(r'Q\d+', qid):
                    continue
                missing_dob = not valid_source_dob(row.get('dob', '').strip())
                missing_height = not valid_source_height(row.get('height', '').strip())
                if missing_dob or missing_height:
                    roster_by_qid[qid].append({
                        'tour': tour, 'player_id': row['player_id'], 'wikidata_id': qid,
                        'missing_dob': missing_dob, 'missing_height': missing_height,
                    })

    qids = sorted(roster_by_qid, key=lambda value: int(value[1:]))
    retrieved = datetime.now(timezone.utc).isoformat(timespec='seconds')
    counters = Counter()
    fieldnames = ['tour', 'player_id', 'wikidata_id', 'date_of_birth_fallback',
                  'height_cm_fallback', 'wikidata_lastrevid', 'retrieved_utc']
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STAGING.unlink(missing_ok=True)
    with gzip.open(STAGING, 'wt', encoding='utf-8', newline='', compresslevel=6) as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for offset in range(0, len(qids), BATCH_SIZE):
            batch = qids[offset:offset + BATCH_SIZE]
            entities = fetch_batch(batch)
            for qid in batch:
                entity = entities.get(qid, {})
                if not entity or entity.get('missing'):
                    counters['entities_missing'] += 1
                    continue
                dob, dob_conflict = birth_date(entity)
                height, height_conflict = height_cm(entity)
                counters['birth_date_conflicts'] += dob_conflict
                counters['height_conflicts'] += height_conflict
                for player in roster_by_qid[qid]:
                    dob_fill = dob if player['missing_dob'] else None
                    height_fill = height if player['missing_height'] else None
                    if not dob_fill and not height_fill:
                        continue
                    writer.writerow({
                        'tour': player['tour'], 'player_id': player['player_id'], 'wikidata_id': qid,
                        'date_of_birth_fallback': dob_fill or '', 'height_cm_fallback': height_fill or '',
                        'wikidata_lastrevid': entity.get('lastrevid', ''), 'retrieved_utc': retrieved,
                    })
                    counters['rows'] += 1
                    counters[f"rows_{player['tour']}"] += 1
                    counters['birth_dates_filled'] += bool(dob_fill)
                    counters['heights_filled'] += bool(height_fill)
                    counters[f"birth_dates_filled_{player['tour']}"] += bool(dob_fill)
                    counters[f"heights_filled_{player['tour']}"] += bool(height_fill)
            counters['batches_completed'] += 1
            if counters['batches_completed'] % 10 == 0:
                print(f"Fetched {counters['batches_completed']}/{(len(qids)+BATCH_SIZE-1)//BATCH_SIZE} Wikidata batches", flush=True)
            if offset + BATCH_SIZE < len(qids):
                time.sleep(0.2)

    STAGING.replace(OUT)
    report = {
        'generated_utc': retrieved,
        'source': 'Wikidata structured data, fetched through the MediaWiki Action API',
        'source_url': 'https://www.wikidata.org/w/api.php',
        'license': 'CC0 for structured data',
        'attribution': 'Wikidata contributors; attribution is appreciated. Player IDs and Wikidata IDs come from the Sackmann CC BY-NC-SA 4.0 rosters.',
        'policy': {
            'only_existing_roster_wikidata_ids': True,
            'only_fills_source_missing_or_invalid_fields': True,
            'birth_date_requires_day_precision': True,
            'birth_date_plausibility_range': ['1850-01-01', date.today().isoformat()],
            'height_units_normalized_to_cm': sorted(HEIGHT_UNITS_TO_CM),
            'height_plausibility_range_cm': [130, 230],
            'conflicting_best_ranked_values_excluded': True,
            'original_roster_rows_modified': False,
        },
        'requested_unique_entities': len(qids),
        'roster_input_sha256': roster_hashes,
        'counts': dict(sorted(counters.items())),
        'request_retries': dict(REQUEST_STATS),
        'output': {
            'path': OUT.relative_to(ROOT).as_posix(), 'rows': counters['rows'],
            'bytes': OUT.stat().st_size, 'sha256': sha256(OUT),
        },
    }
    REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
