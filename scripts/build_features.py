"""Export reproducible pre-match features with a conservative 28-day history embargo."""
import csv
import gzip
import hashlib
import json
import math
import sqlite3
from collections import Counter, defaultdict, deque
from datetime import date, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LAG=28

def number(value):
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError):
        return None

def orientation(row):
    ids=sorted([row['winner_id'],row['loser_id']])
    # No winner label, score or post-match statistics enters the assignment.
    key='|'.join(str(row.get(k) or '') for k in ('tour','tourney_id','match_num','round'))+'|'+'|'.join(ids)
    if hashlib.sha256(key.encode()).digest()[0] % 2:
        ids.reverse()
    return ids

def split_for(day):
    if day < date(2023,1,1)-timedelta(days=LAG):
        return 'train'
    if day < date(2023,1,1):
        return 'purged'
    if day < date(2024,1,1)-timedelta(days=LAG):
        return 'validation'
    if day < date(2024,1,1):
        return 'purged'
    return 'test'

def player_state():
    return {'elo':1500.,'n':0,'wins':0,'surface':{},'svpt':0.,'svwon':0.,
            'aces':0.,'ace_den':0.,'df':0.,'df_den':0.,'latest':None,'recent':deque()}

class History:
    def __init__(self):
        self.players=defaultdict(player_state)
        self.h2h=defaultdict(lambda:[0,0])
        self.pending=deque()

    def queue(self,row,day):
        self.pending.append((day.toordinal(),row))

    def release_before(self,cutoff):
        while self.pending and self.pending[0][0] < cutoff:
            _,row=self.pending.popleft()
            self.update(row)

    def update(self,row):
        tour,surface=row['tour'],row.get('surface') or 'Unknown'
        wid,lid=row['winner_id'],row['loser_id']
        w,l=self.players[(tour,wid)],self.players[(tour,lid)]
        change=32*(1-1/(1+10**max(-15,min(15,(l['elo']-w['elo'])/400))))
        w['elo']+=change
        l['elo']-=change
        ws=w['surface'].setdefault(surface,[1500.,0])
        ls=l['surface'].setdefault(surface,[1500.,0])
        change=32*(1-1/(1+10**max(-15,min(15,(ls[0]-ws[0])/400))))
        ws[0]+=change
        ls[0]-=change
        ws[1]+=1
        ls[1]+=1
        for s,side,won in [(w,'w',1),(l,'l',0)]:
            s['n']+=1
            s['wins']+=won
            s['latest']=row['event_date']
            s['recent'].append((date.fromisoformat(row['event_date']).toordinal(),won))
            pts=number(row.get(side+'_svpt'))
            first=number(row.get(side+'_1stWon'))
            second=number(row.get(side+'_2ndWon'))
            if pts and pts>0:
                if first is not None and second is not None and 0<=first+second<=pts:
                    s['svpt']+=pts
                    s['svwon']+=first+second
                for col,total,denom in [('ace','aces','ace_den'),('df','df','df_den')]:
                    value=number(row.get(side+'_'+col))
                    if value is not None and 0<=value<=pts:
                        s[total]+=value
                        s[denom]+=pts
        a,b=sorted([wid,lid])
        h=self.h2h[(tour,a,b)]
        h[0]+=1
        h[1]+=int(wid==a)

    def profile(self,row,pid,prefix,day):
        s=self.players[(row['tour'],pid)]
        surface=row.get('surface') or 'Unknown'
        se,sn=s['surface'].get(surface,[1500.,0])
        while s['recent'] and s['recent'][0][0]<day.toordinal()-365:
            s['recent'].popleft()
        recent=list(s['recent'])
        result={key:number(row.get(prefix+'_'+key)) for key in ['rank','rank_points','age','ht','seed']}
        result.update(hand=row.get(prefix+'_hand'),elo=round(s['elo'],5),surface_elo=round(se,5),
                      prior_matches=s['n'],prior_win_rate=s['wins']/s['n'] if s['n'] else None,
                      surface_prior_matches=sn,prior_serve_points=s['svpt'],
                      prior_serve_win_rate=s['svwon']/s['svpt'] if s['svpt'] else None,
                      prior_ace_rate=s['aces']/s['ace_den'] if s['ace_den'] else None,
                      prior_double_fault_rate=s['df']/s['df_den'] if s['df_den'] else None,
                      recent365_matches=len(recent),
                      recent365_win_rate=sum(x[1] for x in recent)/len(recent) if recent else None,
                      history_latest_date=s['latest'])
        return result

    def features(self,row,day):
        ids=orientation(row)
        result={k:row.get(k) for k in ['record_id','tour','category','tourney_id','surface','tourney_level','round','best_of']}
        result.update(event_date=day.isoformat(),history_cutoff_exclusive=(day-timedelta(days=LAG)).isoformat(),
                      split=split_for(day),p1_id=ids[0],p2_id=ids[1],p1_won=int(ids[0]==row['winner_id']))
        for label,pid in zip(['p1','p2'],ids):
            prefix='winner' if pid==row['winner_id'] else 'loser'
            result[label+'_name']=row.get(prefix+'_name')
            for key,value in self.profile(row,pid,prefix,day).items():
                result[label+'_'+key]=value
        for key in ['rank','rank_points','age','ht','elo','surface_elo','prior_win_rate',
                    'prior_serve_win_rate','recent365_win_rate']:
            a,b=result['p1_'+key],result['p2_'+key]
            result[key+'_diff']=a-b if a is not None and b is not None else None
        a,b=sorted(ids)
        total,awins=self.h2h[(row['tour'],a,b)]
        result['h2h_prior_matches']=total
        result['p1_h2h_prior_win_rate']=(awins if ids[0]==a else total-awins)/total if total else None
        return result

def main():
    out=ROOT/'data/processed'
    db=sqlite3.connect(out/'tennis.sqlite')
    db.row_factory=sqlite3.Row
    # Exclude conflicting versions of the same fixture; preserve all versions in the DB.
    db.execute("""CREATE TEMP TABLE conflicts AS SELECT tour,tourney_id,match_num,
        min(winner_id,loser_id) AS a,max(winner_id,loser_id) AS b FROM matches
        GROUP BY tour,tourney_id,match_num,min(winner_id,loser_id),max(winner_id,loser_id)
        HAVING count(*)>1""")
    conflict_keys={tuple(r) for r in db.execute('SELECT * FROM conflicts')}
    history=History()
    skipped=Counter()
    counts=Counter()
    metrics=defaultdict(lambda: {'n':0,'correct':0,'brier_sum':0.,'logloss_sum':0.})
    output=out/'model_features.csv.gz'
    temp=out/'model_features.building.csv.gz'
    previous=None
    writer=None
    with gzip.open(temp,'wt',encoding='utf-8',newline='',compresslevel=6) as target:
        for record in db.execute('SELECT * FROM matches ORDER BY event_date,record_id'):
            row=dict(record)
            if row.get('source_extra_cells'):
                skipped['extra_csv_values']+=1
                continue
            if not row['event_date'] or not row['winner_id'] or not row['loser_id'] or row['winner_id']==row['loser_id']:
                skipped['invalid_date_or_players']+=1
                continue
            if row['outcome']!='completed':
                skipped[row['outcome']]+=1
                continue
            a,b=sorted([row['winner_id'],row['loser_id']])
            if (row['tour'],row['tourney_id'],row['match_num'],a,b) in conflict_keys:
                skipped['conflicting_fixture']+=1
                continue
            day=date.fromisoformat(row['event_date'])
            if day!=previous:
                history.release_before(day.toordinal()-LAG)
                previous=day
            result=history.features(row,day)
            if writer is None:
                writer=csv.DictWriter(target,fieldnames=list(result))
                writer.writeheader()
            writer.writerow(result)
            counts[result['split']]+=1
            prob=1/(1+10**max(-15,min(15,-result['elo_diff']/400)))
            y=result['p1_won']
            m=metrics[result['split']]
            m['n']+=1
            m['correct']+=int((prob>=.5)==bool(y))
            m['brier_sum']+=(prob-y)**2
            m['logloss_sum']+=-(y*math.log(max(prob,1e-15))+(1-y)*math.log(max(1-prob,1e-15)))
            history.queue(row,day)
            if sum(counts.values())%100000==0:
                print(f'Exported {sum(counts.values()):,} feature rows',flush=True)
    temp.replace(output)
    summary={}
    for split,m in metrics.items():
        n=m['n']
        summary[split]={'rows':n,'elo_accuracy':m['correct']/n,'elo_brier':m['brier_sum']/n,'elo_log_loss':m['logloss_sum']/n}
    report={'embargo_days':LAG,'rows_by_split':dict(counts),'excluded':dict(skipped),'elo_baseline':summary,
            'interpretation':'Offline historical benchmark; no guarantee of future performance. Source tournament dates approximate availability.'}
    (out/'feature_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    db.close()
    print(json.dumps(report,indent=2),flush=True)

if __name__=='__main__':
    main()

