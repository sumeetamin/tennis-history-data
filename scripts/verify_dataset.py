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

def valid_source_dob(value):
    try:
        parsed=datetime.strptime(str(value or ''),'%Y%m%d').date()
        return date(1850,1,1)<=parsed<=datetime.now(timezone.utc).date()
    except ValueError:
        return False

def valid_source_height(value):
    try:
        return 130<=float(value)<=230
    except (TypeError,ValueError):
        return False

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
odds_by_record={}
with gzip.open(link_path,'rt',encoding='utf-8',newline='') as src:
    for row in csv.DictReader(src):
        linked_rows+=1
        assert row['match_id'] not in linked_odds_ids
        linked_odds_ids.add(row['match_id'])
        assert row['sackmann_record_id'] and row['link_method'] and row['score_match_basis']
        match=db.execute('''SELECT tour,winner_id,loser_id,winner_name,loser_name,score,
                    winner_rank,loser_rank,winner_rank_points,loser_rank_points
                FROM matches WHERE record_id=?''',
                         (row['sackmann_record_id'],)).fetchone()
        assert match is not None
        assert row['genre']==match[0]
        assert row['vainqueur_id'] in (row['joueur1_id'],row['joueur2_id'])
        linked_winner=row['joueur1'] if row['vainqueur_id']==row['joueur1_id'] else row['joueur2']
        assert norm(linked_winner)==norm(match[3])
        assert row['sackmann_score']==match[5]
        actual=score_sets(row['score'])
        archive=score_sets(match[5])
        p1_won=row['vainqueur_id']==row['joueur1_id']
        expected=archive if p1_won else tuple((b,a) for a,b in archive)
        assert actual and actual==expected
        linked_match_ids[row['sackmann_record_id']]+=1
        odds_by_record[row['sackmann_record_id']]={
            'odds':row, 'winner_id':str(match[1]), 'loser_id':str(match[2]), 'match':match,
        }
assert linked_rows==link_report['counts']['linked_score_and_winner_verified']
duplicate_archive_links=sum(count>1 for count in linked_match_ids.values())
assert duplicate_archive_links==0

# Validate the keyed weekly-ranking supplement and its pre-event provenance.
rank_fallback_path=ROOT/'data/processed/supplements/ranking_fallbacks.csv.gz'
rank_fallback_report_path=ROOT/'data/processed/supplements/ranking_fallbacks_report.json'
rank_fallback_report=json.loads(rank_fallback_report_path.read_text(encoding='utf-8'))
assert sha256(rank_fallback_path)==rank_fallback_report['output']['sha256']
assert rank_fallback_path.stat().st_size==rank_fallback_report['output']['bytes']
assert sha256(out/'tennis.sqlite')==rank_fallback_report['input']['sha256']
rank_fallbacks={}
rank_fallback_rank_fills=0
rank_fallback_points_fills=0
with gzip.open(rank_fallback_path,'rt',encoding='utf-8',newline='') as src:
    for row in csv.DictReader(src):
        record_id=row['record_id']
        assert record_id not in rank_fallbacks
        match=db.execute('''SELECT tour,category,event_date,tourney_id,match_num,round,
                    winner_id,loser_id,winner_rank,loser_rank,winner_rank_points,loser_rank_points
                FROM matches WHERE record_id=?''',(record_id,)).fetchone()
        assert match is not None
        assert row['tour']==match[0] and row['event_date']==match[2]
        ordered=sorted((str(match[6]),str(match[7])))
        orientation_key='|'.join([str(match[i] or '') for i in (0,3,4,5)]+ordered)
        if hashlib.sha256(orientation_key.encode()).digest()[0] % 2:
            ordered.reverse()
        assert (row['p1_id'],row['p2_id'])==tuple(ordered)
        source_values={str(match[6]):(match[8],match[10]),str(match[7]):(match[9],match[11])}
        event_day=date.fromisoformat(match[2])
        has_fill=False
        for side,player_id in (('p1',row['p1_id']),('p2',row['p2_id'])):
            rank_fallback=row[f'{side}_rank_fallback']
            points_fallback=row[f'{side}_rank_points_fallback']
            snapshot_day=row[f'{side}_rank_snapshot_date']
            if rank_fallback or points_fallback:
                assert snapshot_day
                assert snapshot_day < event_day.strftime('%Y%m%d')
                age=(event_day-date.fromisoformat(f'{snapshot_day[:4]}-{snapshot_day[4:6]}-{snapshot_day[6:8]}')).days
                assert 0 < age <= rank_fallback_report['policy']['maximum_snapshot_age_days']
                weekly=db.execute('''SELECT rank,points,ranking_date FROM rankings
                    WHERE tour=? AND player=? AND ranking_date<? ORDER BY ranking_date DESC LIMIT 1''',
                    (row['tour'],player_id,event_day.strftime('%Y%m%d'))).fetchone()
                assert weekly is not None and weekly[2]==snapshot_day
                original_rank,original_points=source_values[player_id]
                if rank_fallback:
                    assert not original_rank or float(original_rank)<=0
                    assert weekly[0] and float(weekly[0])>0 and float(rank_fallback)==float(weekly[0])
                    rank_fallback_rank_fills+=1
                    has_fill=True
                if points_fallback:
                    assert not original_points or not str(original_points).strip()
                    assert weekly[1] and float(weekly[1])>0 and float(points_fallback)==float(weekly[1])
                    rank_fallback_points_fills+=1
                    has_fill=True
            else:
                assert not rank_fallback and not points_fallback
        assert has_fill
        rank_fallbacks[record_id]=row
assert len(rank_fallbacks)==rank_fallback_report['output']['rows']
assert len(rank_fallbacks)==rank_fallback_report['rows_with_at_least_one_fallback']

# Validate Wikidata profile values against the existing roster IDs and missing fields.
profile_enrichment_path=ROOT/'data/processed/supplements/player_profile_enrichment.csv.gz'
profile_enrichment_report_path=ROOT/'data/processed/supplements/player_profile_enrichment_report.json'
profile_enrichment_report=json.loads(profile_enrichment_report_path.read_text(encoding='utf-8'))
assert sha256(profile_enrichment_path)==profile_enrichment_report['output']['sha256']
assert profile_enrichment_path.stat().st_size==profile_enrichment_report['output']['bytes']
source_hashes={item['path']:item['sha256'] for item in manifest['files']}
expected_roster_hashes={path:source_hashes[path] for path in (
    'atp/atp_players.csv','wta/wta_players.csv')}
expected_roster_hashes={
    f'data/raw/sackmann-archive/{path}':digest
    for path,digest in expected_roster_hashes.items()
}
assert profile_enrichment_report['roster_input_sha256']==expected_roster_hashes
profile_rows=0
profile_dob_fills=0
profile_height_fills=0
profile_keys=set()
with gzip.open(profile_enrichment_path,'rt',encoding='utf-8',newline='') as src:
    for row in csv.DictReader(src):
        key=(row['tour'],row['player_id'])
        assert key not in profile_keys
        profile_keys.add(key)
        original=db.execute('SELECT wikidata_id,dob,height FROM players WHERE tour=? AND player_id=?',key).fetchone()
        assert original is not None and original[0]==row['wikidata_id']
        assert re.fullmatch(r'Q\d+',row['wikidata_id'])
        assert int(row['wikidata_lastrevid'])>0
        dob=row['date_of_birth_fallback']
        height=row['height_cm_fallback']
        if dob:
            assert not valid_source_dob(original[1])
            parsed=datetime.strptime(dob,'%Y-%m-%d').date()
            assert date(1850,1,1)<=parsed<=datetime.now(timezone.utc).date()
            profile_dob_fills+=1
        if height:
            try:
                height_value=float(height)
            except ValueError:
                assert False, f'Invalid Wikidata height: {height}'
            assert not valid_source_height(original[2])
            assert height_value.is_integer() and 130<=height_value<=230
            profile_height_fills+=1
        assert dob or height
        profile_rows+=1
assert profile_rows==profile_enrichment_report['output']['rows']
assert profile_dob_fills==profile_enrichment_report['counts']['birth_dates_filled']
assert profile_height_fills==profile_enrichment_report['counts']['heights_filled']

# Validate the optional pre-match feature table with prices in deterministic p1/p2 orientation.
odds_feature_path=ROOT/'data/odds/model_features_with_odds.csv.gz'
odds_feature_report=json.loads((ROOT/'data/odds/model_features_with_odds_report.json').read_text(encoding='utf-8'))
assert sha256(odds_feature_path)==odds_feature_report['output']['sha256']
assert sha256(link_path)==odds_feature_report['inputs'][link_path.name]
assert sha256(odds_path)==odds_feature_report['inputs'][odds_path.name]
assert sha256(rank_fallback_path)==odds_feature_report['inputs'][rank_fallback_path.relative_to(ROOT).as_posix()]
assert sha256(out/'tennis.sqlite')==odds_feature_report['inputs']['tennis.sqlite']
for filename,digest in odds_feature_report['inputs']['yearly_feature_csv_sha256'].items():
    assert sha256(ROOT/'data/processed/model_features_by_year'/filename)==digest
odds_feature_rows=0
odds_feature_records=set()
odds_feature_ids=set()
odds_open_pairs=0
odds_close_pairs=0
with gzip.open(odds_feature_path,'rt',encoding='utf-8',newline='') as src:
    feature_reader=csv.DictReader(src)
    odds_feature_columns=feature_reader.fieldnames or []
    expected_odds_columns=['odds_provider_match_id','odds_match_date_utc','odds_open_p1_decimal','odds_open_p2_decimal',
                           'odds_last_pre_match_p1_decimal','odds_last_pre_match_p2_decimal',
                           'odds_open_pair_available','odds_last_pre_match_pair_available',
                           'p1_rank_source','p1_rank_points_source','p1_rank_snapshot_date',
                           'p2_rank_source','p2_rank_points_source','p2_rank_snapshot_date']
    assert odds_feature_columns[-len(expected_odds_columns):]==expected_odds_columns
    assert not {'winner_id','loser_id','score','minutes','odds_winner_id','odds_score'} & set(odds_feature_columns)
    for row in feature_reader:
        odds_feature_rows+=1
        record_id=row['record_id']
        assert record_id in odds_by_record
        assert record_id not in odds_feature_records
        odds_feature_records.add(record_id)
        match_odds=odds_by_record[record_id]['odds']
        assert row['odds_provider_match_id']==match_odds['match_id']
        assert row['odds_match_date_utc']==match_odds['date']
        p1_archive_id=(odds_by_record[record_id]['winner_id']
                       if match_odds['vainqueur_id']==match_odds['joueur1_id']
                       else odds_by_record[record_id]['loser_id'])
        p2_archive_id=(odds_by_record[record_id]['loser_id']
                       if match_odds['vainqueur_id']==match_odds['joueur1_id']
                       else odds_by_record[record_id]['winner_id'])
        assert {row['p1_id'],row['p2_id']}=={p1_archive_id,p2_archive_id}
        assert row['p1_id']!=row['p2_id']
        assert int(row['p1_won'])==int(row['p1_id']==odds_by_record[record_id]['winner_id'])
        odds_feature_ids.add(row['odds_provider_match_id'])
        if row['p1_id']==p1_archive_id:
            expected_prices=(match_odds['cote1_ouverture'],match_odds['cote2_ouverture'],
                             match_odds['cote1_cloture'],match_odds['cote2_cloture'])
        else:
            expected_prices=(match_odds['cote2_ouverture'],match_odds['cote1_ouverture'],
                             match_odds['cote2_cloture'],match_odds['cote1_cloture'])
        actual_prices=(row['odds_open_p1_decimal'],row['odds_open_p2_decimal'],
                       row['odds_last_pre_match_p1_decimal'],row['odds_last_pre_match_p2_decimal'])
        assert actual_prices==expected_prices
        open_pair=bool(expected_prices[0] and expected_prices[1])
        close_pair=bool(expected_prices[2] and expected_prices[3])
        assert row['odds_open_pair_available']==str(open_pair).lower()
        assert row['odds_last_pre_match_pair_available']==str(close_pair).lower()
        fallback=rank_fallbacks.get(record_id)
        archive_match=odds_by_record[record_id]['match']
        raw_values={str(archive_match[1]):(archive_match[6],archive_match[8]),
                    str(archive_match[2]):(archive_match[7],archive_match[9])}
        for side in ('p1','p2'):
            source_player=row[f'{side}_id']
            raw_rank,raw_points=raw_values[source_player]
            expected_rank_source='match_record' if raw_rank and float(raw_rank)>0 else 'missing'
            expected_points_source='match_record' if raw_points and str(raw_points).strip() else 'missing'
            rank_value=fallback.get(f'{side}_rank_fallback','') if fallback else ''
            points_value=fallback.get(f'{side}_rank_points_fallback','') if fallback else ''
            if expected_rank_source=='missing' and rank_value:
                expected_rank_source='weekly_snapshot'
                assert float(row[f'{side}_rank'])==float(rank_value)
            if expected_points_source=='missing' and points_value:
                expected_points_source='weekly_snapshot'
                assert float(row[f'{side}_rank_points'])==float(points_value)
            assert row[f'{side}_rank_source']==expected_rank_source
            assert row[f'{side}_rank_points_source']==expected_points_source
            expected_snapshot=(fallback.get(f'{side}_rank_snapshot_date','') if fallback and
                               (expected_rank_source=='weekly_snapshot' or expected_points_source=='weekly_snapshot') else '')
            assert row[f'{side}_rank_snapshot_date']==expected_snapshot
        odds_open_pairs+=open_pair
        odds_close_pairs+=close_pair
assert odds_feature_rows==odds_feature_report['rows']
assert len(odds_feature_ids)==odds_feature_rows
assert odds_open_pairs==odds_feature_report['opening_odds_pair_rows']
assert odds_close_pairs==odds_feature_report['last_pre_match_odds_pair_rows']
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
result['odds_feature_rows_checked']=odds_feature_rows
result['odds_feature_provider_ids_unique']=len(odds_feature_ids)==odds_feature_rows
result['odds_feature_opening_pairs_checked']=odds_open_pairs
result['odds_feature_last_pre_match_pairs_checked']=odds_close_pairs
result['ranking_fallback_rows_checked']=len(rank_fallbacks)
result['ranking_fallback_rank_values_checked']=rank_fallback_rank_fills
result['ranking_fallback_points_values_checked']=rank_fallback_points_fills
result['wikidata_profile_enrichment_rows_checked']=profile_rows
result['wikidata_birth_dates_checked']=profile_dob_fills
result['wikidata_heights_checked']=profile_height_fills
result['odds_feature_rank_sources_checked']=odds_feature_rows*2
recent_path=ROOT/'data/odds/recent_model_features.csv.gz'
recent_report_path=ROOT/'data/odds/recent_model_features_report.json'
recent_report=json.loads(recent_report_path.read_text(encoding='utf-8'))
recent_rows=0
recent_ids=set()
recent_min=recent_max=''
with gzip.open(recent_path,'rt',encoding='utf-8',newline='') as src:
    recent_reader=csv.DictReader(src)
    recent_columns=recent_reader.fieldnames or []
    assert not {'winner_id','loser_id','score','minutes','winner_name','loser_name'} & set(recent_columns)
    for row in recent_reader:
        recent_rows+=1
        rid=row['record_id']
        assert rid.startswith('vb:') and rid not in recent_ids
        recent_ids.add(rid)
        day=date.fromisoformat(row['event_date'])
        cutoff=date.fromisoformat(row['history_cutoff_exclusive'])
        assert cutoff==day-timedelta(days=28)
        tour=row['tour']
        archive_max=date.fromisoformat(recent_report['archive_max_event_date'][tour])
        assert day>archive_max+timedelta(days=recent_report['date_buffer_days'])
        assert row['p1_id'] and row['p2_id'] and row['p1_id']!=row['p2_id']
        assert row['p1_won'] in {'0','1'}
        for side in ('p1','p2'):
            latest=row[f'{side}_history_latest_date']
            assert not latest or date.fromisoformat(latest)<cutoff
        for col in ('odds_open_p1_decimal','odds_open_p2_decimal','odds_close_p1_decimal','odds_close_p2_decimal'):
            assert not row[col] or float(row[col])>1
        recent_min=min(recent_min,row['event_date']) if recent_min else row['event_date']
        recent_max=max(recent_max,row['event_date'])
assert recent_rows==recent_report['total_rows']
assert sha256(recent_path)==recent_report['sha256']
assert ([recent_min,recent_max] if recent_rows else None)==recent_report['date_range']
result['recent_model_feature_rows_checked']=recent_rows
result['recent_model_feature_sha256_checked']=True
(out/'validation_report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result,indent=2))

