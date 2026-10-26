"""Reject daily dataset edits unless the committed bytes remain an exact prefix."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = (
    'data/odds/atp_wta_match_odds.csv',
    'data/odds/recent_model_features.csv.gz',
    'data/odds/recent_ranking_fallbacks.csv.gz',
    'data/odds/recent_player_profiles.csv.gz',
)


def verify_prefix(path, original):
    """Return appended byte count; reject truncation or any changed original byte."""
    with path.open('rb') as stream:
        if stream.read(len(original)) != original:
            raise ValueError(f'Append-only violation: existing bytes changed or removed in {path}')
    return path.stat().st_size - len(original)


def main():
    for name in DATASETS:
        original = subprocess.check_output(['git', 'cat-file', 'blob', f'HEAD:{name}'], cwd=ROOT)
        appended = verify_prefix(ROOT / name, original)
        print(f'{name}: committed bytes preserved; {appended:,} bytes appended')


if __name__ == '__main__':
    main()
