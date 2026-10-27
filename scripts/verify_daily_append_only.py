"""Reject daily dataset edits unless the committed bytes remain an exact prefix."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = (
    'data/odds/atp_wta_match_odds.csv',
    'data/odds/recent_model_features.csv.gz',
    'data/odds/recent_ranking_fallbacks.csv.gz',
    'data/odds/recent_player_profiles.csv.gz',
    'data/odds/recent_odds_corrections.csv',
    'data/curated/main_tour/atp_wta_main_tour_model_features.csv.gz',
)


def verify_prefix(path, original):
    """Return appended byte count; reject truncation or any changed original byte."""
    with path.open('rb') as stream:
        if stream.read(len(original)) != original:
            raise ValueError(f'Append-only violation: existing bytes changed or removed in {path}')
    return path.stat().st_size - len(original)


def main():
    curated = subprocess.check_output([
        'git', 'ls-tree', '-r', '--name-only', 'HEAD', '--',
        'data/curated/post_2000/matches', 'data/curated/post_2000/players.csv.gz',
        'data/curated/post_2000/player_identity_candidates.csv.gz',
    ], cwd=ROOT, text=True).splitlines()
    for name in (*DATASETS, *curated):
        original = subprocess.check_output(['git', 'cat-file', 'blob', f'HEAD:{name}'], cwd=ROOT)
        appended = verify_prefix(ROOT / name, original)
        print(f'{name}: committed bytes preserved; {appended:,} bytes appended')


if __name__ == '__main__':
    main()
