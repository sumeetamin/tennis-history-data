import csv
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from build_odds_quote_table import FIELDS as ODDS_FIELDS, append_gzip, decimal, make_quote_id, read_gzip, timing_fields
from build_point_history_experiment import feature_player_id, prior_count
from build_coverage_dashboard import draw_population, history_bin
from update_point_by_point_supplement import safe_rate, round_from_match_id


class DataContractTests(unittest.TestCase):
    def test_unknown_rate_is_missing_not_zero(self):
        self.assertEqual(safe_rate(0, 0), '')
        self.assertEqual(safe_rate(0, 15), '0')

    def test_source_round_fallback_is_labeled(self):
        self.assertEqual(round_from_match_id('2024-wimbledon-2701'), ('f', 'match_id_bracket_code'))
        self.assertEqual(round_from_match_id('unrecognized'), ('', 'unavailable'))

    def test_population_keeps_qualifiers_and_challengers_separate(self):
        self.assertEqual(draw_population({'round': 'Q1'}), 'qualifier')
        self.assertEqual(draw_population({'category': 'qual_chall', 'tourney_level': 'C'}), 'challenger_main_draw')
        self.assertEqual(draw_population({'category': 'tour', 'tourney_level': 'A'}), 'atp_wta_tour_main_draw')

    def test_odds_quote_identity_handles_duplicate_provider_match_ids(self):
        first = make_quote_id('595808', 2, 'opening', 'player-a', 1)
        second = make_quote_id('595808', 3, 'opening', 'player-a', 1)
        self.assertNotEqual(first, second)
        self.assertEqual(first, make_quote_id('595808', 2, 'opening', 'player-a', 1))

    def test_quote_timestamps_remain_unknown_without_source_evidence(self):
        self.assertIn('quote_timestamp_utc', ODDS_FIELDS)
        values = timing_fields()
        self.assertEqual(values['quote_timestamp_utc'], '')
        self.assertEqual(values['match_timezone'], '')
        self.assertEqual(values['result_available_at_utc'], '')
        self.assertEqual(values['quote_timestamp_status'], 'not_provided_by_source')

    def test_bad_or_missing_odds_are_not_coerced(self):
        self.assertEqual(decimal(''), ('', 'missing'))
        self.assertEqual(decimal('not-a-price'), ('', 'invalid'))
        self.assertEqual(decimal('1.01'), ('1.01', 'valid'))

    def test_quote_partition_appends_without_rewriting_published_bytes(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            path = Path(folder) / 'odds.csv.gz'
            append_gzip(path, ['quote_id', 'price'], [{'quote_id': 'a', 'price': '2.1'}])
            original = path.read_bytes()
            append_gzip(path, ['quote_id', 'price'], [{'quote_id': 'b', 'price': '1.9'}])
            self.assertTrue(path.read_bytes().startswith(original))
            self.assertEqual([row['quote_id'] for row in read_gzip(path)], ['a', 'b'])

    def test_odds_partitions_fit_github_single_file_limit(self):
        manifest = ROOT / 'data/odds/quotes/manifest.json'
        if not manifest.exists():
            self.skipTest('Quote export has not been generated yet.')
        details = json.loads(manifest.read_text(encoding='utf-8'))
        for path, info in details.get('files', {}).items():
            self.assertLess(info['bytes'], 100_000_000, path)

    def test_point_history_excludes_values_at_exclusive_cutoff(self):
        self.assertEqual(prior_count(['2020-01-01', '2020-01-05', '2020-01-09'], '2020-01-05'), 1)

    def test_crosswalk_ids_map_to_feature_id_namespace(self):
        self.assertEqual(feature_player_id('wta', 'sackmann:wta:206252'), '206252')
        self.assertEqual(feature_player_id('wta', 'other-id'), 'other-id')

    def test_generated_supplement_aliases_are_not_misrepresented_as_reviewed(self):
        path = ROOT / 'data/curated/point_by_point/player_aliases.csv.gz'
        if not path.exists():
            self.skipTest('Point-by-point supplement has not been generated yet.')
        with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
            row = next(csv.DictReader(stream))
        corrections = ROOT / 'data/curated/point_by_point/corrections.csv.gz'
        if corrections.exists():
            with gzip.open(corrections, 'rt', encoding='utf-8', newline='') as stream:
                for correction in csv.DictReader(stream):
                    if correction['table_name'] == path.name and correction['record_key'] == row['alias_key']:
                        row = json.loads(correction['new_row_json'])
        self.assertEqual(row['human_reviewed'], '0')
        self.assertIn('automatic', row['verification_status'])


if __name__ == '__main__':
    unittest.main()
