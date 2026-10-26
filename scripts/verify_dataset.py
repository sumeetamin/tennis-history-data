"""Check imported source hashes and exported feature chronology/labels."""
import csv
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'data/processed'
manifest=json.loads((ROOT/'data/source_files.json').read_text(encoding='utf-8'))
for item in manifest['files']:
    with (ROOT/'data/raw/sackmann-archive'/item['path']).open('rb') as src:
        assert hashlib.file_digest(src,'sha256').hexdigest()==item['sha256'],item['path']
db=sqlite3.connect(out/'tennis.sqlite')
counts=Counter()
labels=Counter()
previous=''
sampled=0
with gzip.open(out/'model_features.csv.gz','rt',encoding='utf-8',newline='') as src:
    for i,row in enumerate(csv.DictReader(src)):
        assert row['event_date']>=previous
        previous=row['event_date']
        cutoff=row['history_cutoff_exclusive']
        assert date.fromisoformat(cutoff)==date.fromisoformat(row['event_date'])-timedelta(days=28)
        for p in ['p1','p2']:
            assert not row[p+'_history_latest_date'] or row[p+'_history_latest_date']<cutoff
        assert row['p1_id']!=row['p2_id']
        assert row['p1_won'] in ('0','1')
        counts[row['split']]+=1
        labels[row['p1_won']]+=1
        if i%1000==0:
            original=db.execute('SELECT winner_id,loser_id,outcome FROM matches WHERE record_id=?',(row['record_id'],)).fetchone()
            assert set(original[:2])=={row['p1_id'],row['p2_id']}
            assert int(row['p1_won'])==int(row['p1_id']==original[0])
            assert original[2]=='completed'
            sampled+=1
report=json.loads((out/'feature_report.json').read_text())
assert dict(counts)==report['rows_by_split']
assert set(labels)=={'0','1'}
result={'source_files_hash_checked':len(manifest['files']),
        'feature_rows_temporally_checked':sum(counts.values()),
        'label_rows_checked_against_db':sampled,'label_counts':dict(labels),'passed':True}
(out/'validation_report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))

