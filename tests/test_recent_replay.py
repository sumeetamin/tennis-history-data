"""Ensure incremental exports retain prior results and obey the history embargo."""
import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_features import History
from build_recent_odds_features import replay_recent


def candidate(day, number, winner='10', loser='20'):
    row = dict(record_id=f'vb:{number}', tour='atp', event_date=day, winner_id=winner,
               loser_id=loser, tourney_id=f'event:{number}', match_num=str(number),
               round='F', surface='Hard', category='tour')
    return date.fromisoformat(day), row, {}


def export(candidates, existing=()):
    return [item[3] for item in replay_recent(History(), candidates, set(existing))]


class RecentReplay(unittest.TestCase):
    def test_two_runs_equal_one_batch_for_new_rows(self):
        rows = [candidate('2026-06-16', 1), candidate('2026-07-20', 2, '20', '10'),
                candidate('2026-08-25', 3)]
        all_at_once = export(rows)
        second_run = export(rows, {'vb:1', 'vb:2'})
        self.assertEqual(second_run, all_at_once[2:])
        self.assertEqual(second_run[0]['p1_prior_matches'], 2)
        self.assertEqual(second_run[0]['h2h_prior_matches'], 2)

    def test_boundary_and_same_day_remain_excluded(self):
        rows = [candidate('2026-06-16', 1), candidate('2026-07-14', 2),
                candidate('2026-07-15', 3), candidate('2026-07-15', 4)]
        fresh = export(rows, {'vb:1'})
        self.assertEqual([row['p1_prior_matches'] for row in fresh], [0, 1, 1])

    def test_late_missing_match_is_placed_by_event_date(self):
        rows = [candidate('2026-08-25', 3), candidate('2026-06-16', 1), candidate('2026-07-20', 2)]
        result = export(rows, {'vb:1', 'vb:3'})
        self.assertEqual([row['record_id'] for row in result], ['vb:2'])
        self.assertEqual(result[0]['p1_prior_matches'], 1)
        self.assertEqual(result[0]['p1_history_latest_date'], '2026-06-16')

    def test_no_new_ids_yields_nothing(self):
        self.assertEqual(export([candidate('2026-06-16', 1)], {'vb:1'}), [])


if __name__ == '__main__':
    unittest.main()
