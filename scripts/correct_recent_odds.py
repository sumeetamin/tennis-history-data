"""Append explicit price corrections without changing published feature rows."""
import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
from recent_odds_mapping import aligned_prices

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'data/odds'
OUT = BASE / 'recent_odds_corrections.csv'
REPORT = BASE / 'recent_odds_corrections_report.json'
PRICES = ['odds_open_p1_decimal', 'odds_open_p2_decimal', 'odds_close_p1_decimal', 'odds_close_p2_decimal']
FIELDS = ['record_id', 'provider_match_id', 'p1_id', 'p2_id', 'source_player_for_p1', *PRICES, 'reason']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def same(a, b):
    if a in ('', None) or b in ('', None):
        return a in ('', None) and b in ('', None)
    return float(a) == float(b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    with gzip.open(BASE / 'recent_model_features.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
        features = list(csv.DictReader(stream))
    ids = {row['odds_provider_match_id'] for row in features}
    sources = {}
    with (BASE / 'atp_wta_match_odds.csv').open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['match_id'] in ids:
                if row['match_id'] in sources:
                    raise ValueError('Duplicate provider match ID')
                sources[row['match_id']] = row
    corrections = {}
    if OUT.exists():
        with OUT.open(encoding='utf-8', newline='') as stream:
            for row in csv.DictReader(stream):
                if row['record_id'] in corrections:
                    raise ValueError('Duplicate correction ID')
                corrections[row['record_id']] = row
    expected_ids = set()
    additions = []
    changed_values = 0
    for feature in features:
        raw = sources[feature['odds_provider_match_id']]
        direct = (feature['p1_name'], feature['p2_name']) == (raw['joueur1'], raw['joueur2'])
        reverse = (feature['p1_name'], feature['p2_name']) == (raw['joueur2'], raw['joueur1'])
        if direct == reverse or feature['tour'] != raw['genre'].lower():
            raise ValueError(f"Ambiguous identity for {feature['record_id']}")
        p1_provider = raw['joueur1_id'] if direct else raw['joueur2_id']
        if feature['p1_won'] != str(int(raw['vainqueur_id'] == p1_provider)):
            raise ValueError('Source winner disagrees with feature label')
        prices = aligned_prices(raw, direct)
        # Independently check price-side selection by player name, including missing prices.
        for field in PRICES:
            model_side = 1 if '_p1_' in field else 2
            name = feature[f'p{model_side}_name']
            side = 1 if name == raw['joueur1'] else 2
            period = 'ouverture' if '_open_' in field else 'cloture'
            value = raw[f'cote{side}_{period}']
            try:
                value = float(value)
                if not math.isfinite(value) or value <= 1:
                    value = None
            except ValueError:
                value = None
            if not same(prices[field], value):
                raise ValueError('Independent orientation check failed')
        different = [field for field in PRICES if not same(feature[field], prices[field])]
        if not different:
            continue
        changed_values += len(different)
        expected_ids.add(feature['record_id'])
        result = dict(record_id=feature['record_id'], provider_match_id=raw['match_id'],
                      p1_id=feature['p1_id'], p2_id=feature['p2_id'], source_player_for_p1='1' if direct else '2',
                      **{field: '' if prices[field] is None else str(prices[field]) for field in PRICES},
                      reason='explicit_source_player_alignment_and_valid_decimal_prices')
        old = corrections.get(feature['record_id'])
        if old is not None and old != result:
            raise ValueError('Existing correction differs from authoritative source; manual review required')
        if old is None:
            additions.append(result)
    if set(corrections) - expected_ids:
        raise ValueError('Orphan or unnecessary existing correction')
    if args.verify_only:
        if additions:
            raise ValueError(f'{len(additions)} missing corrections')
    else:
        exists = OUT.exists()
        with OUT.open('a', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
            if not exists:
                writer.writeheader()
            writer.writerows(additions)
    report = dict(feature_rows_checked=len(features), corrected_rows=len(expected_ids), corrected_price_values=changed_values,
                  source_sha256=sha(BASE / 'atp_wta_match_odds.csv'), feature_sha256=sha(BASE / 'recent_model_features.csv.gz'),
                  corrections_sha256=sha(OUT), policy='Join on record_id and replace all four odds fields for matched rows, including blanks. Existing feature bytes remain unchanged.')
    if args.verify_only:
        stored = json.loads(REPORT.read_text(encoding='utf-8'))
        if stored != report:
            raise ValueError('Correction report mismatch')
    else:
        REPORT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
