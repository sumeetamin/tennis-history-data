import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from build_features import History, orientation, split_for
from build_dataset import outcome, date_iso, category

def match(**overrides):
    row=dict(tour='atp',tourney_id='2020-x',match_num='1',round='F',
             winner_id='10',loser_id='20',event_date='2020-01-01',surface='Hard',
             record_id='fixture',category='tour',winner_rank='2',loser_rank='4')
    row.update(overrides)
    return row

class TemporalFeatures(unittest.TestCase):
    def test_orientation_independent_of_result(self):
        self.assertEqual(orientation(match()),orientation(match(winner_id='20',loser_id='10')))
    def test_embargo_excludes_boundary(self):
        h=History()
        h.queue(match(),date(2020,1,1))
        h.release_before(date(2020,1,1).toordinal())
        self.assertEqual(h.players[('atp','10')]['n'],0)
        h.release_before(date(2020,1,2).toordinal())
        self.assertEqual(h.players[('atp','10')]['n'],1)
        self.assertGreater(h.players[('atp','10')]['elo'],1500)
    def test_queued_results_do_not_change_features(self):
        h=History()
        later=match(event_date='2020-01-20')
        before=h.features(later,date(2020,1,20))
        h.queue(match(),date(2020,1,1))
        h.release_before((date(2020,1,20)).toordinal()-28)
        after=h.features(later,date(2020,1,20))
        self.assertEqual(before,after)
    def test_tours_are_namespaced(self):
        h=History()
        h.update(match())
        self.assertEqual(h.players[('wta','10')]['n'],0)
    def test_split_purge(self):
        self.assertEqual(split_for(date(2022,12,1)),'train')
        self.assertEqual(split_for(date(2022,12,15)),'purged')
        self.assertEqual(split_for(date(2023,1,1)),'validation')
        self.assertEqual(split_for(date(2023,12,15)),'purged')
        self.assertEqual(split_for(date(2024,1,1)),'test')
    def test_source_status_and_dates(self):
        self.assertEqual(outcome('6-3 2-1 RET'),'retirement')
        self.assertEqual(outcome('W/O'),'walkover')
        self.assertEqual(outcome('6-4 7-6(2)'),'completed')
        self.assertEqual(outcome(''),'unknown')
        self.assertIsNone(date_iso('20261301'))
        self.assertEqual(category('wta_matches_qual_itf_2020.csv'),'qual_itf')

if __name__=='__main__':
    unittest.main()

