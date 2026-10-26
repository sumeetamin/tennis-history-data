"""Import a pinned archive, preserving source bytes; Python 3.10+, no dependencies."""
import argparse
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REVISION = '83733587353df8a41f2fd4f516147d5aa83f5a8d'
DEST = ROOT / 'data/raw/sackmann-archive'

def wanted(name):
    return name in ('README.md', 'LICENSE') or name.startswith(('atp/', 'wta/'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, help='Existing clone containing the pinned revision')
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    if args.checkout:
        paths = subprocess.check_output(['git', '-C', str(args.checkout), 'ls-tree', '-r', '--name-only', REVISION], text=True).splitlines()
        with subprocess.Popen(['git', '-C', str(args.checkout), 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
            for name in filter(wanted, paths):
                proc.stdin.write(f'{REVISION}:{name}\n'.encode())
                proc.stdin.flush()
                header = proc.stdout.readline().decode().split()
                if len(header) != 3 or header[1] != 'blob':
                    raise RuntimeError(f'Missing source blob: {name}: {header}')
                target = DEST / name
                target.parent.mkdir(parents=True, exist_ok=True)
                remaining = int(header[2])
                with target.open('wb') as out:
                    while remaining:
                        chunk = proc.stdout.read(min(remaining, 1024 * 1024))
                        if not chunk:
                            raise RuntimeError('Truncated git blob')
                        out.write(chunk)
                        remaining -= len(chunk)
                if proc.stdout.read(1) != b'\n':
                    raise RuntimeError('Invalid git batch response')
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError('Git export failed')
    else:
        url = f'https://github.com/Aneeshers/tennis-sackmann-archive/archive/{REVISION}.zip'
        with tempfile.TemporaryDirectory(prefix='tennis-download-') as temp:
            archive_path = Path(temp) / 'source.zip'
            request = urllib.request.Request(url, headers={'User-Agent': 'tennis-history-data/1.0'})
            with urllib.request.urlopen(request, timeout=120) as response, archive_path.open('wb') as out:
                shutil.copyfileobj(response, out)
            with zipfile.ZipFile(archive_path) as archive:
                for item in archive.infolist():
                    parts = PurePosixPath(item.filename).parts
                    if item.is_dir() or len(parts) < 2:
                        continue
                    if '..' in parts or PurePosixPath(item.filename).is_absolute():
                        raise ValueError('Unsafe archive path')
                    name = '/'.join(parts[1:])
                    if wanted(name):
                        target = DEST / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(item) as src, target.open('wb') as out:
                            shutil.copyfileobj(src, out)
    for required in ('LICENSE', 'README.md', 'atp/atp_players.csv', 'wta/wta_players.csv'):
        if not (DEST / required).is_file():
            raise RuntimeError(f'Incomplete import: missing {required}')
    print(f'Imported pinned source {REVISION} to {DEST}', flush=True)

if __name__ == '__main__':
    main()

