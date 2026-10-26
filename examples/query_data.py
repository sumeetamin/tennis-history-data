"""Print recent matches from the local SQLite database."""
import argparse
import json
import sqlite3
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--player',default='Novak Djokovic',help='Exact source player name')
p.add_argument('--limit',type=int,default=10)
a=p.parse_args()
db=sqlite3.connect(Path(__file__).resolve().parents[1]/'data/processed/tennis.sqlite')
db.row_factory=sqlite3.Row
rows=db.execute("""SELECT tour,event_date,tourney_name,surface,round,winner_name,loser_name,score
 FROM matches WHERE winner_name=? OR loser_name=? ORDER BY event_date DESC LIMIT ?""",(a.player,a.player,a.limit))
print(json.dumps([dict(r) for r in rows],indent=2,ensure_ascii=False))

