import sys
import unittest
import tempfile
from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from curated_quality import completed_result, decimal_price, orient_score, profile_height
from build_curated_dataset import AppendTable, read_gzip, source_manifest_sha


class CuratedQualityTests(unittest.TestCase):
    def row(self, score, **changes):
        return dict(joueur1_id='1', joueur2_id='2', vainqueur_id='1', score=score,
                    genre='wta', categorie='Main tour') | changes

    def test_result_and_score_must_agree(self):
        self.assertEqual(completed_result(self.row('6-4 7-6(5)')), 'completed')
        self.assertEqual(completed_result(self.row('4-6 6-7(5)')), 'winner_score_disagreement')

    def test_rejects_false_set_completion_and_extra_sets(self):
        self.assertNotEqual(completed_result(self.row('8-2 6-4')), 'completed')
        self.assertNotEqual(completed_result(self.row('6-4 6-3 0-6')), 'completed')
        self.assertNotEqual(completed_result(self.row('6-4 5-3')), 'completed')
        self.assertNotEqual(completed_result(self.row('6-4 6-3 garbage')), 'completed')

    def test_slam_and_advantage_decider(self):
        self.assertNotEqual(completed_result(self.row('6-4 6-3', genre='atp', categorie='Grand Chelem')), 'completed')
        self.assertEqual(completed_result(self.row('6-4 3-6 6-4 4-6 10-8', genre='atp', categorie='Grand Chelem')), 'completed')
        self.assertEqual(completed_result(self.row('6-4 4-6 10-8')), 'completed')

    def test_price_and_orientation(self):
        for value in ('nan', 'inf', '0', '1', '-3', 'unknown'):
            self.assertEqual(decimal_price(value), '')
        self.assertEqual(decimal_price('2.30'), '2.30')
        self.assertEqual(orient_score('4-6 6-7(5)', False), '6-4 7-6(5)')

    def test_implausible_heights_are_not_guessed(self):
        for value in ('3', '15', '71', 'nan', '', None):
            self.assertEqual(profile_height(value), '')
        self.assertEqual(profile_height('185'), '185')

    def test_append_preserves_bytes_and_rejects_changes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root = Path(folder)
            target = root / 'published.csv.gz'
            stage = root / 'stage'
            stage.mkdir()
            def run(rows):
                with ExitStack() as stack:
                    table = AppendTable(target, ['id', 'value'], 'id', stage, stack)
                    for row in rows:
                        table.add(row)
                table.check()
                table.publish()
            first = dict(id='1', value='original')
            run([first])
            old_bytes = target.read_bytes()
            run([first])
            self.assertEqual(target.read_bytes(), old_bytes)
            run([first, dict(id='2', value='backfill')])
            self.assertTrue(target.read_bytes().startswith(old_bytes))
            self.assertEqual(len(list(read_gzip(target))), 2)
            unchanged = target.read_bytes()
            with self.assertRaises(ValueError):
                run([dict(id='1', value='modified')])
            self.assertEqual(target.read_bytes(), unchanged)

    def test_source_manifest_hash_survives_git_line_endings(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root = Path(folder)
            (root / 'data').mkdir()
            path = root / 'data/source_files.json'
            with patch('build_curated_dataset.ROOT', root):
                path.write_bytes(b'{\n  "files": []\n}\n')
                before = source_manifest_sha()
                path.write_bytes(b'{\r\n  "files": []\r\n}\r\n')
                self.assertEqual(source_manifest_sha(), before)


if __name__ == '__main__':
    unittest.main()
