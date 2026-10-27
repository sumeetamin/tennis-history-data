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
    supplement_paths = subprocess.check_output([
        'git', 'ls-tree', '-r', '--name-only', 'HEAD', '--',
        'data/odds/quotes/by_year', 'data/odds/quotes/odds_quote_corrections.csv.gz',
        'data/curated/point_by_point',
        'data/experimental/point_history/point_history_pre_match_features.csv.gz',
        'data/experimental/point_history/feature_corrections.csv.gz',
    ], cwd=ROOT, text=True).splitlines()
    append_only_supplements = [
        name for name in supplement_paths
        if name.endswith('.csv.gz') and (
            name.startswith('data/odds/quotes/by_year/') or
            name == 'data/odds/quotes/odds_quote_corrections.csv.gz' or
            name.startswith('data/curated/point_by_point/') or
            name.startswith('data/experimental/point_history/')
        )
    ]
    for name in (*DATASETS, *curated, *append_only_supplements):
        original = subprocess.check_output(['git', 'cat-file', 'blob', f'HEAD:{name}'], cwd=ROOT)
        appended = verify_prefix(ROOT / name, original)
        print(f'{name}: committed bytes preserved; {appended:,} bytes appended')


if __name__ == '__main__':
    main()
