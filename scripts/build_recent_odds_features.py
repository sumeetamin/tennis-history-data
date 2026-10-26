"""Append model features for settled post-archive matches with verified player IDs."""
import csv
import gzip
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_features import History, orientation, LAG  # noqa: E402
from odds_quality import settlement_status  # noqa: E402
from recent_odds_mapping import aligned_prices

ODDS = ROOT / "data/odds/atp_wta_match_odds.csv"
CROSSWALK = ROOT / "data/odds/linked_odds_sackmann.csv.gz"
DB = ROOT / "data/processed/tennis.sqlite"
OUT = ROOT / "data/odds/recent_model_features.csv.gz"
REPORT = ROOT / "data/odds/recent_model_features_report.json"


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def surface(value):
    value = (value or "").casefold()
    if "terre" in value or "clay" in value:
        return "Clay"
    if "gazon" in value or "grass" in value:
        return "Grass"
    if "moquette" in value or "carpet" in value:
        return "Carpet"
    if "dur" in value or "hard" in value:
        return "Hard"
    return None


def main():
    aliases, names = defaultdict(set), defaultdict(set)
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        linked = {}
        with gzip.open(CROSSWALK, "rt", encoding="utf-8", newline="") as src:
            for row in csv.DictReader(src):
                linked[row["sackmann_record_id"]] = row
        ids = list(linked)
        archive_players = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" for _ in chunk)
            for r in db.execute(f"SELECT record_id,tour,winner_id,loser_id FROM matches WHERE record_id IN ({marks})", chunk):
                archive_players[r["record_id"]] = (r["tour"], str(r["winner_id"]), str(r["loser_id"]))
        for rid, link in linked.items():
            if rid not in archive_players:
                continue
            tour, winner, loser = archive_players[rid]
            p1, p2 = str(link["joueur1_id"]), str(link["joueur2_id"])
            if link["vainqueur_id"] == p1:
                canon = (winner, loser)
            elif link["vainqueur_id"] == p2:
                canon = (loser, winner)
            else:
                continue
            for provider, canonical, name in ((p1, canon[0], link.get("joueur1")), (p2, canon[1], link.get("joueur2"))):
                key = (tour, provider)
                aliases[key].add(canonical)
                names[key].add(norm(name))
        aliases = {k: next(iter(v)) for k, v in aliases.items() if len(v) == 1}
        archive_max = {tour: date.fromisoformat(day) for tour, day in db.execute("SELECT tour,max(event_date) FROM matches WHERE event_date IS NOT NULL GROUP BY tour")}
        conflicts = {tuple(r) for r in db.execute("""SELECT tour,tourney_id,match_num,min(winner_id,loser_id),max(winner_id,loser_id)
            FROM matches GROUP BY tour,tourney_id,match_num,min(winner_id,loser_id),max(winner_id,loser_id) HAVING count(*)>1""")}
        history = History()
        last_day = None
        for record in db.execute("SELECT * FROM matches ORDER BY event_date,record_id"):
            row = dict(record)
            if not row.get("event_date") or row.get("outcome") != "completed" or not row.get("winner_id") or not row.get("loser_id"):
                continue
            a, b = sorted((row["winner_id"], row["loser_id"]))
            if (row["tour"], row["tourney_id"], row["match_num"], a, b) in conflicts:
                continue
            day = date.fromisoformat(row["event_date"])
            if day != last_day:
                history.release_before(day.toordinal() - LAG)
                last_day = day
            history.queue(row, day)

        existing = set()
        all_dates = []
        if OUT.exists():
            with gzip.open(OUT, "rt", encoding="utf-8", newline="") as src:
                for r in csv.DictReader(src):
                    existing.add(r["record_id"])
                    all_dates.append(r["event_date"])
        candidates = []
        counters = defaultdict(int)
        with ODDS.open(encoding="utf-8", newline="") as src:
            for raw in csv.DictReader(src):
                mid = raw.get("match_id", "")
                if not mid or "vb:" + mid in existing:
                    continue
                tour = (raw.get("genre") or "").casefold()
                if tour not in archive_max or not raw.get("date"):
                    continue
                try:
                    day = date.fromisoformat(raw["date"][:10])
                except ValueError:
                    counters["invalid_date"] += 1
                    continue
                if day > datetime.now(timezone.utc).date():
                    counters["future_dated"] += 1
                    continue
                if day <= archive_max[tour] + timedelta(days=14):
                    continue
                if settlement_status(raw) != "completed":
                    continue
                p1, p2 = str(raw.get("joueur1_id") or ""), str(raw.get("joueur2_id") or "")
                k1, k2 = (tour, p1), (tour, p2)
                if k1 not in aliases or k2 not in aliases or norm(raw.get("joueur1")) not in names[k1] or norm(raw.get("joueur2")) not in names[k2]:
                    counters["unverified_identity"] += 1
                    continue
                winner_provider = str(raw.get("vainqueur_id") or "")
                if winner_provider not in {p1, p2}:
                    continue
                winner = aliases[(tour, winner_provider)]
                loser = aliases[k2 if winner_provider == p1 else k1]
                if winner == loser:
                    continue
                row = {
                    "record_id": "vb:" + mid, "tour": tour,
                    "category": (raw.get("categorie") or "").casefold().replace(" ", "_"),
                    "tourney_id": "valuebetennis:" + str(raw.get("tournoi_id") or ""),
                    "tourney_name": raw.get("tournoi"), "event_date": day.isoformat(),
                    "surface": surface(raw.get("surface")), "tourney_level": None,
                    "round": None, "best_of": "5" if tour == "atp" and "chelem" in (raw.get("categorie") or "").casefold() else "3",
                    "match_num": mid, "winner_id": winner, "loser_id": loser,
                    "winner_name": raw.get("joueur1") if winner_provider == p1 else raw.get("joueur2"),
                    "loser_name": raw.get("joueur2") if winner_provider == p1 else raw.get("joueur1"),
                    "outcome": "completed",
                }
                for side in ("winner", "loser"):
                    for stat in ("svpt", "1stWon", "2ndWon", "ace", "df"):
                        row[f"{side}_{stat}"] = None
                candidates.append((day, row, raw))
        candidates.sort(key=lambda x: (x[0], x[1]["record_id"]))

        written, fields = [], None
        for day, row, raw in candidates:
            history.release_before(day.toordinal() - LAG)
            f = history.features(row, day)
            odds_p1 = str(raw.get("joueur1_id"))
            source_is_p1 = aliases[(row["tour"], odds_p1)] == f["p1_id"]
            prices = aligned_prices(raw, source_is_p1)
            for field in ("odds_open_p1_decimal", "odds_open_p2_decimal", "odds_close_p1_decimal", "odds_close_p2_decimal"):
                f[field] = prices[field]
            f.update(odds_provider="Valuebetennis", odds_provider_match_id=raw["match_id"], odds_match_date_utc=raw["date"])
            fields = fields or list(f)
            written.append(f)
            all_dates.append(f["event_date"])
            history.queue(row, day)
        if written:
            exists = OUT.exists()
            with gzip.open(OUT, "at" if exists else "wt", encoding="utf-8", newline="", compresslevel=6) as dest:
                writer = csv.DictWriter(dest, fieldnames=fields)
                if not exists:
                    writer.writeheader()
                writer.writerows(written)
        total_rows = len(existing) + len(written)
        digest = hashlib.sha256(OUT.read_bytes()).hexdigest() if OUT.exists() else None
        report = {"total_rows": total_rows,
                  "date_buffer_days": 14, "history_embargo_days": LAG,
                  "archive_max_event_date": {k: v.isoformat() for k, v in archive_max.items()},
                  "skipped_unverified_identity": counters["unverified_identity"],
                  "future_dated_rows_skipped": counters["future_dated"],
                  "date_range": [min(all_dates), max(all_dates)] if all_dates else None,
                  "sha256": digest,
                  "feature_file": "data/odds/recent_model_features.csv.gz",
                  "policy": "Strict crosswalk-derived player IDs and matching observed names only; completed scores dated no later than the current UTC date; immutable append-only output. No match scores, outcomes, or post-match statistics are features."}
        REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
