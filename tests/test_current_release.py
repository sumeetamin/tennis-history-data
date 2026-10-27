import csv
import gzip
import hashlib
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_current_recent_snapshot import check_row, write_gzip
from build_recent_features_enriched import merge, price
from build_research_release import normalize
from audit_repository_quality import available


class CurrentReleaseTests(unittest.TestCase):
    def feature(self):
        return dict(record_id='vb:1', tour='wta', event_date='2026-10-26', p1_id='a', p2_id='b',
                    p1_won='1', history_cutoff_exclusive='2026-09-28', p1_history_latest_date='2026-09-27',
                    p2_history_latest_date='', category='main_tour', round='', p1_hand='U')

    def raw(self):
        return dict(match_id='1', date='2026-10-26 12:00:00', genre='wta', categorie='Main Tour',
                    tour='5', joueur1_id='x', joueur2_id='y', vainqueur_id='x', score='6-3 6-4')

    def test_reject_unfinished_or_future_match(self):
        check_row(self.feature(), self.raw(), date(2026, 10, 27))
        raw = self.raw(); raw['score'] = '6-3 2-1'
        with self.assertRaises(ValueError):
            check_row(self.feature(), raw, date(2026, 10, 27))
        with self.assertRaises(ValueError):
            check_row(self.feature(), self.raw(), date(2026, 10, 25))

    def test_embargo_boundary_is_exclusive(self):
        row = self.feature(); row['p1_history_latest_date'] = row['history_cutoff_exclusive']
        with self.assertRaises(ValueError):
            check_row(row, self.raw(), date(2026, 10, 27))

    def test_supplement_identity_mismatch_is_rejected(self):
        rank = self.feature(); rank['p1_id'] = 'wrong'
        with self.assertRaises(ValueError):
            merge(self.feature(), self.raw(), rank, None)

    def test_same_day_rank_is_rejected(self):
        rank = self.feature(); rank.update(p1_rank_fallback='10', p1_rank_snapshot_date='2026-10-26', p1_rank_age_days='0')
        with self.assertRaises(ValueError):
            merge(self.feature(), self.raw(), rank, None)

    def test_unknown_hand_and_round_remain_unknown(self):
        row = merge(self.feature(), self.raw(), None, None)
        self.assertEqual(row['p1_hand'], '')
        self.assertEqual(row['draw_status'], 'unknown')
        self.assertEqual(row['round'], '')
        self.assertFalse(available('p1_hand', 'U'))
        self.assertTrue(available('p1_prior_matches', '0'))

    def test_final_can_be_classified_and_quote_time_is_missing(self):
        raw = self.raw(); raw['tour'] = '12'
        row = merge(self.feature(), raw, None, None)
        self.assertEqual(row['round'], 'F')
        self.assertEqual(row['draw_status'], 'main_draw')
        self.assertEqual(row['odds_quote_timestamp_utc'], '')
        self.assertEqual(row['odds_timestamp_verified'], 'false')

    def test_decimal_odds_must_exceed_one(self):
        for value in ('nan', 'inf', '0', '1', '-2', ''):
            self.assertIsNone(price(value))
        self.assertEqual(price('2.5'), 2.5)

    def test_deterministic_gzip_and_round_trip(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temp:
            a, b = Path(temp) / 'a.gz', Path(temp) / 'b.gz'
            write_gzip(a, ['record_id'], [{'record_id': 'vb:1'}])
            write_gzip(b, ['record_id'], [{'record_id': 'vb:1'}])
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with gzip.open(a, 'rt', encoding='utf8') as stream:
                self.assertEqual(list(csv.DictReader(stream)), [{'record_id': 'vb:1'}])


if __name__ == '__main__':
    unittest.main()
