"""Split the generated feature export into GitHub-sized year files."""
import csv
import gzip
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'data/processed/model_features.csv.gz'
DEST=ROOT/'data/processed/model_features_by_year_upload'

def main():
    if not SOURCE.is_file():
        raise SystemExit('Build features first: python scripts/build_features.py')
    DEST.mkdir(parents=True,exist_ok=True)
    counts={}
    current_year=None
    target=None
    writer=None
    with gzip.open(SOURCE,'rt',encoding='utf-8',newline='') as src:
        reader=csv.DictReader(src)
        for row in reader:
            year=row['event_date'][:4]
            if year!=current_year:
                if target:
                    target.close()
                current_year=year
                target=gzip.open(DEST/f'model_features_{year}.csv.gz','wt',encoding='utf-8',newline='',compresslevel=6)
                writer=csv.DictWriter(target,fieldnames=reader.fieldnames)
                writer.writeheader()
                counts[year]=0
            writer.writerow(row)
            counts[year]+=1
        if target:
            target.close()
    for year,count in counts.items():
        print(f'{year}: {count:,} rows',flush=True)
    print(f'Wrote {sum(counts.values()):,} rows across {len(counts)} yearly files to {DEST}')

if __name__=='__main__':
    main()

