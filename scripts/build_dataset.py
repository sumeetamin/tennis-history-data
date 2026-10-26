"""Build SQLite tables and a measured coverage report from the pinned CSV archive."""
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/sackmann-archive'
OUT = ROOT / 'data/processed'
REVISION = '83733587353df8a41f2fd4f516147d5aa83f5a8d'
META = ['record_id','tour','category','source_file','source_row','event_date','outcome']

def category(name):
    for value in ['doubles', 'qual_chall', 'qual_itf', 'futures', 'amateur']:
        if value in name:
            return value
    return 'tour'

@lru_cache(maxsize=50000)
def date_iso(value):
    try:
        return datetime.strptime(value, '%Y%m%d').date().isoformat()
    except (ValueError, TypeError):
        return None

def outcome(score):
    text = (score or '').upper()
    if 'W/O' in text or 'WO' == text.strip():
        return 'walkover'
    if 'RET' in text:
        return 'retirement'
    if 'DEF' in text:
        return 'default'
    if 'ABD' in text or 'ABN' in text or 'UNF' in text:
        return 'abandoned'
    return 'completed' if re.match(r'^\d', text.strip()) else 'unknown'

def headers(paths):
    result = []
    for path in paths:
        with path.open(encoding='utf-8-sig', newline='') as src:
            for field in next(csv.reader(src)):
                if not re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*', field):
                    raise ValueError(f'Invalid source column: {field!r}')
                if field not in result:
                    result.append(field)
    return result

def create_table(db, name, fields, primary):
    cols = ','.join('"' + f + '" TEXT' for f in fields)
    db.execute(f'CREATE TABLE "{name}" ({cols}, PRIMARY KEY ({primary}))')
    return f'INSERT OR IGNORE INTO "{name}" VALUES ({",".join("?" for _ in fields)})'

def main():
    if not (RAW / 'LICENSE').exists():
        raise SystemExit('Fetch the licensed source first: python scripts/fetch_sackmann.py')
    OUT.mkdir(parents=True, exist_ok=True)
    stage = OUT / 'tennis.building.sqlite'
    if stage.exists():
        raise SystemExit('A previous staging DB exists. Inspect it before rebuilding.')
    db = sqlite3.connect(stage)
    db.execute('PRAGMA journal_mode=OFF')
    db.execute('PRAGMA synchronous=OFF')
    files = sorted(RAW.glob('*/*.csv'))
    groups = {
        'matches': [p for p in files if '_matches_' in p.name and 'doubles' not in p.name],
        'doubles': [p for p in files if '_matches_doubles_' in p.name],
        'players': [p for p in files if p.name.endswith('_players.csv')],
        'rankings': [p for p in files if '_rankings_' in p.name],
    }
    manifest = []
    totals = {}
    invalid_dates = Counter()
    extra_cell_rows = Counter()
    for table, paths in groups.items():
        source_fields = headers(paths)
        extra = META if table in ('matches', 'doubles') else ['tour','source_file','source_row']
        fields = extra + ['source_extra_cells'] + source_fields
        primary = 'record_id' if table in ('matches','doubles') else ('tour,player_id' if table=='players' else 'tour,ranking_date,player')
        sql = create_table(db, table, fields, primary)
        read_count = 0
        for path in paths:
            tour = path.parent.name
            rel = path.relative_to(RAW).as_posix()
            batch = []
            count = 0
            with path.open(encoding='utf-8-sig', newline='') as src:
                for row_number, row in enumerate(csv.DictReader(src), 2):
                    count += 1
                    trailing = row.pop(None, [])
                    if trailing:
                        extra_cell_rows[table] += 1
                    if any(value for value in trailing):
                        row['source_extra_cells'] = json.dumps(trailing)
                    row.update(tour=tour, source_file=rel, source_row=str(row_number))
                    if table in ('matches','doubles'):
                        cat = category(path.name)
                        event_date = date_iso(row.get('tourney_date'))
                        if not event_date:
                            invalid_dates[table] += 1
                        # Exact payload deduplication; conflicting records are retained for audit.
                        payload = {k:row.get(k) or '' for k in source_fields}
                        key = json.dumps([tour,payload,row.get('source_extra_cells')], sort_keys=True, separators=(',',':'))
                        row.update(record_id=hashlib.sha256(key.encode()).hexdigest(), category=cat,
                                   event_date=event_date, outcome=outcome(row.get('score')))
                    batch.append([row.get(f) or None for f in fields])
                    if len(batch) >= 5000:
                        db.executemany(sql,batch)
                        batch.clear()
                if batch:
                    db.executemany(sql,batch)
            read_count += count
            manifest.append({'path':rel,'bytes':path.stat().st_size,'rows':count,
                             'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),
                             'url':f'https://github.com/Aneeshers/tennis-sackmann-archive/blob/{REVISION}/{rel}'})
        db.commit()
        unique = db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        totals[table] = {'source_rows':read_count,'rows':unique,'duplicate_keys_omitted':read_count-unique}
        print(f'{table}: {unique:,} records ({read_count-unique:,} duplicate keys omitted)',flush=True)
    db.execute('CREATE INDEX matches_date ON matches(event_date,record_id)')
    db.execute('CREATE INDEX matches_winner ON matches(tour,winner_id,event_date)')
    db.execute('CREATE INDEX matches_loser ON matches(tour,loser_id,event_date)')
    db.execute('CREATE INDEX rankings_player_date ON rankings(tour,player,ranking_date)')
    db.execute('CREATE INDEX matches_event ON matches(tour,tourney_id)')
    db.execute("""CREATE VIEW tournament_editions AS
        SELECT tour,tourney_id,tourney_name,event_date,surface,tourney_level,
        count(*) AS match_records FROM matches GROUP BY tour,tourney_id,tourney_name,event_date,surface,tourney_level""")
    coverage = db.execute("""SELECT tour,category,substr(event_date,1,4) AS year,
        count(*) AS matches,
        sum(CASE WHEN CAST(w_svpt AS REAL)>0 AND CAST(l_svpt AS REAL)>0 THEN 1 ELSE 0 END) AS serve_stats_rows,
        sum(CASE WHEN CAST(winner_rank AS REAL)>0 AND CAST(loser_rank AS REAL)>0 THEN 1 ELSE 0 END) AS both_ranked_rows,
        min(event_date),max(event_date)
        FROM matches GROUP BY tour,category,year ORDER BY tour,category,year""").fetchall()
    with (OUT/'coverage.csv').open('w',encoding='utf-8',newline='') as out:
        writer=csv.writer(out)
        writer.writerow(['tour','category','year','matches','both_serve_stats','both_ranked','first_event_date','last_event_date'])
        writer.writerows(coverage)
    ranges=db.execute('SELECT tour,category,count(*),min(event_date),max(event_date) FROM matches GROUP BY tour,category').fetchall()
    conflicts=db.execute("""SELECT count(*) FROM (SELECT tour,tourney_id,match_num,winner_id,loser_id,count(*) AS n
        FROM matches GROUP BY tour,tourney_id,match_num,winner_id,loser_id HAVING n>1)""").fetchone()[0]
    orphan=db.execute("""SELECT count(*) FROM (
        SELECT tour,winner_id AS id FROM matches WHERE winner_id IS NOT NULL
        UNION SELECT tour,loser_id FROM matches WHERE loser_id IS NOT NULL
        ) p LEFT JOIN players b ON p.tour=b.tour AND p.id=b.player_id WHERE b.player_id IS NULL""").fetchone()[0]
    integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
    report={'source_revision':REVISION,'generated_at':datetime.now(timezone.utc).isoformat(),
            'tables':totals,'invalid_event_dates':dict(invalid_dates),'extra_csv_cell_rows':dict(extra_cell_rows),'potential_conflicting_match_keys':conflicts,
            'match_player_ids_missing_roster':orphan,'sqlite_integrity':integrity,
            'source_files':len(manifest),'source_bytes':sum(f['bytes'] for f in manifest)}
    (OUT/'build_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (ROOT/'data/source_files.json').write_text(json.dumps({'revision':REVISION,'files':manifest},indent=2),encoding='utf-8')
    text=['# Measured dataset coverage','',f'Source revision: {REVISION}. Counts measured from the imported records.',
          '', '| Tour | File category | Match records | Earliest event date | Latest event date |',
          '|---|---|---:|---|---|']
    text += [f'| {t} | {c} | {n:,} | {lo} | {hi} |' for t,c,n,lo,hi in ranges]
    text += ['', 'These are observed ranges, not proof of complete coverage. Event dates are usually tournament start dates, not exact match dates.',
             'See data/processed/coverage.csv for yearly counts, ranking availability and serve-stat availability.',
             'Post-2000 match-stat and player-profile completeness is summarized in docs/post-2000-coverage.md and data/processed/post_2000_coverage_report.json (generate with scripts/profile_coverage.py).',
             '', f'Player records: {totals["players"]["rows"]:,}. Ranking records: {totals["rankings"]["rows"]:,}. Doubles records: {totals["doubles"]["rows"]:,}.',
             f'Potential conflicting match keys: {conflicts:,}. IDs absent from the master player tables: {orphan:,}.',
             'Original files preserve every source row. The normalized ranking table keeps the first occurrence of each tour/date/player key.',
             'Exact duplicate match payloads are collapsed; conflicting payloads remain in the database and are excluded from the model export.',
             'Pre-Open Era ATP records are present in the amateur file; this snapshot does not provide a complete pre-1968 history of all majors.',
             'The match archive is a fixed snapshot. Separately attributed settled singles odds from 2021 onward are maintained in data/odds; the daily workflow appends newly published rows without revising existing ones.']
    (ROOT/'docs/coverage.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    db.commit()
    db.close()
    stage.replace(OUT/'tennis.sqlite')
    print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':
    main()

