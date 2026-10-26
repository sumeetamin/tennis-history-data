"""Check imported source hashes and exported feature chronology/labels."""
import csv
import gzip
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from odds_quality import settlement_status
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'data/processed'

def sha256(path):
    with path.open('rb') as src:
        return hashlib.file_digest(src,'sha256').hexdigest()

def norm(value):
    text=''.join(c for c in unicodedata.normalize('NFKD',value or '') if c.isascii()).lower()
    return re.sub(r'[^a-z0-9]','',text)

def score_sets(value):
    return tuple((int(a),int(b)) for a,b in re.findall(r'(\d+)\s*[-–]\s*(\d+)',value or ''))

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

# Validate the mutable, append-only odds export against its manifest's live totals.
odds_path=ROOT/'data/odds/atp_wta_match_odds.csv'
odds_manifest=json.loads((ROOT/'data/odds/valuebetennis_manifest.json').read_text(encoding='utf-8'))
odds_rows=0
odds_ids=set()
odds_duplicates=0
odds_tours=Counter()
odds_years=Counter()
odds_score_states=Counter()
odds_future_rows=[]
today_utc=datetime.now(timezone.utc).date().isoformat()
with odds_path.open(encoding='utf-8-sig',newline='') as src:
    for row in csv.DictReader(src):
        odds_rows+=1
        match_id=row.get('match_id') or ''
        if match_id in odds_ids:
            odds_duplicates+=1
        odds_ids.add(match_id)
        odds_tours[(row.get('genre') or '').lower()]+=1
        odds_years[(row.get('date') or '')[:4]]+=1
        odds_score_states[settlement_status(row)]+=1
        match_day=(row.get('date') or '')[:10]
        if match_day>today_utc:
            odds_future_rows.append({key:row.get(key,'') for key in ('match_id','date','tournoi','categorie','genre','joueur1','joueur2','score')})
assert odds_duplicates==odds_manifest.get('duplicate_match_ids_in_file',0)
assert odds_rows==odds_manifest['rows']
assert dict(sorted(odds_tours.items()))==odds_manifest['rows_by_tour']
assert dict(sorted(odds_years.items()))==odds_manifest['rows_by_year']
assert odds_path.stat().st_size==odds_manifest['combined_bytes']
assert sha256(odds_path)==odds_manifest['combined_sha256']

# Validate every published odds crosswalk link back to its canonical source row.
link_path=ROOT/'data/odds/linked_odds_sackmann.csv.gz'
link_report=json.loads((ROOT/'data/odds/odds_link_report.json').read_text(encoding='utf-8'))
assert sha256(link_path)==link_report['outputs'][link_path.name]['sha256']
linked_rows=0
linked_odds_ids=set()
linked_match_ids=Counter()
with gzip.open(link_path,'rt',encoding='utf-8',newline='') as src:
    for row in csv.DictReader(src):
        linked_rows+=1
        assert row['match_id'] not in linked_odds_ids
        linked_odds_ids.add(row['match_id'])
        assert row['sackmann_record_id'] and row['link_method'] and row['score_match_basis']
        match=db.execute('''SELECT tour,winner_name,loser_name,score FROM matches WHERE record_id=?''',
                         (row['sackmann_record_id'],)).fetchone()
        assert match is not None
        assert row['genre']==match[0]
        assert row['vainqueur_id'] in (row['joueur1_id'],row['joueur2_id'])
        linked_winner=row['joueur1'] if row['vainqueur_id']==row['joueur1_id'] else row['joueur2']
        assert norm(linked_winner)==norm(match[1])
        assert row['sackmann_score']==match[3]
        actual=score_sets(row['score'])
        archive=score_sets(match[3])
        p1_won=row['vainqueur_id']==row['joueur1_id']
        expected=archive if p1_won else tuple((b,a) for a,b in archive)
        assert actual and actual==expected
        linked_match_ids[row['sackmann_record_id']]+=1
assert linked_rows==link_report['counts']['linked_score_and_winner_verified']
duplicate_archive_links=sum(count>1 for count in linked_match_ids.values())
assert duplicate_archive_links==0
result={'source_files_hash_checked':len(manifest['files']),
        'feature_rows_temporally_checked':sum(counts.values()),
        'label_rows_checked_against_db':sampled,'label_counts':dict(labels),'passed':True}
result['odds_rows_checked']=odds_rows
result['odds_duplicate_match_ids']=odds_duplicates
result['odds_link_rows_checked']=linked_rows
result['odds_links_to_repeated_archive_rows']=duplicate_archive_links
result['odds_manifest_sha256_checked']=True
result['odds_crosswalk_sha256_checked']=True
result['odds_score_state_counts']=dict(sorted(odds_score_states.items()))
result['odds_future_dated_rows_as_of_utc_date']=odds_future_rows
(out/'validation_report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))

