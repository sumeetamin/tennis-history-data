"""Link the attributed 2025 multi-bookmaker odds sample to archive matches."""
import csv
import gzip
import hashlib
import json
import math
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/odds/sources/atp_wta_2025_closing_odds.csv"
DB = ROOT / "data/processed/tennis.sqlite"
OUT = ROOT / "data/odds/multi_bookmaker_consensus_2025.csv.gz"
REPORT = ROOT / "data/odds/multi_bookmaker_consensus_2025_report.json"
MODEL_OUT = ROOT / "data/odds/model_features_with_consensus_odds_2025.csv.gz"
MAX_DATE_GAP = 14
SOURCE_SHA256 = "05ad12b646e55eba9b626b2860cfb98dd6fc869c173e3b9d7dec2016bfb58c20"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def norm(value: str | None) -> str:
    ascii_text = "".join(c for c in unicodedata.normalize("NFKD", value or "") if c.isascii())
    return re.sub(r"[^a-z0-9]", "", ascii_text.lower())


def short_key(value: str | None) -> tuple[str, str] | None:
    """Convert an abbreviated 'Surname A.' source name into surname + initial."""
    parts = (value or "").strip().split()
    if len(parts) < 2:
        return None
    initial = norm(parts[-1])
    surname = norm(" ".join(parts[:-1]))
    if len(initial) != 1 or not surname:
        return None
    return surname, initial


def full_keys(value: str | None) -> set[tuple[str, str]]:
    """Possible surname/first-initial keys for a full archive player name."""
    parts = (value or "").strip().split()
    keys = set()
    # Names in the odds source abbreviate given names and retain the surname;
    # testing every suffix handles compound surnames without guessing a boundary.
    for start in range(1, len(parts)):
        initial = norm(parts[0])[:1]
        surname = norm(" ".join(parts[start:]))
        if initial and surname:
            keys.add((surname, initial))
    return keys


def score_sets(value: str | None) -> tuple[tuple[int, int], ...]:
    return tuple((int(a), int(b)) for a, b in re.findall(r"(\d+)\s*[-–]\s*(\d+)", value or ""))


def best_close_flags(row):
    flags = []
    for side in (1, 2):
        try:
            value = float(row[f"best_close_odds{side}"])
            fair = float(row[f"close_fair_odds{side}"])
            if not math.isfinite(value) or value <= 1:
                flags.append(f"source_p{side}_invalid_best_close")
            elif value > 2 * fair:
                flags.append(f"source_p{side}_best_close_above_twice_fair")
        except (ValueError, KeyError):
            flags.append(f"source_p{side}_missing_best_close")
    return flags


def validate_consensus(row):
    for period in ("open", "close"):
        p, a, b = (float(row[key]) for key in (f"{period}_prob1", f"{period}_fair_odds1", f"{period}_fair_odds2"))
        if not all(math.isfinite(x) for x in (p, a, b)) or not 0 < p < 1 or min(a, b) <= 1:
            raise ValueError(f"Invalid consensus market: {row['match_id']}")
        if abs(1 / a - p) > .001 or abs(1 / b - (1 - p)) > .001:
            raise ValueError(f"Inconsistent fair odds: {row['match_id']}")
    if not math.isfinite(float(row["prob_move_pts"])) or not math.isfinite(float(row["margin_pct"])):
        raise ValueError(f"Nonfinite market metadata: {row['match_id']}")


def read_features() -> dict[str, dict[str, str]]:
    result = {}
    for year in (2024, 2025):
        path = ROOT / f"data/processed/model_features_by_year/model_features_{year}.csv.gz"
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["record_id"] in result:
                    raise ValueError("Duplicate historical feature record_id")
                result[row["record_id"]] = row
    return result


def main() -> None:
    if not SOURCE.is_file() or not DB.is_file():
        raise SystemExit("Pinned source CSV or local SQLite archive is missing.")
    if digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("Source bytes differ from the reviewed pinned dataset")
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as stream:
        source_rows = list(csv.DictReader(stream))
    for row in source_rows:
        validate_consensus(row)
    dates = [date.fromisoformat(row["date_utc"]) for row in source_rows]
    start = (min(dates) - timedelta(days=MAX_DATE_GAP)).isoformat()
    end = (max(dates) + timedelta(days=MAX_DATE_GAP)).isoformat()
    feature_rows = read_features()
    matches_by_pair = defaultdict(list)
    with sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        for row in db.execute("""SELECT record_id,tour,tourney_name,event_date,winner_id,loser_id,
                winner_name,loser_name,score,surface,outcome FROM matches
                WHERE event_date >= ? AND event_date <= ?""", (start, end)):
            winner_keys = full_keys(row["winner_name"])
            loser_keys = full_keys(row["loser_name"])
            for wk in winner_keys:
                for lk in loser_keys:
                    if wk == lk:
                        continue
                    matches_by_pair[(row["tour"], tuple(sorted((wk, lk))))].append(dict(row))

    counts = Counter()
    candidates_by_record = defaultdict(list)
    source_ids = set()
    for odds in source_rows:
        counts["source_rows"] += 1
        odds_id = odds.get("match_id", "")
        if not odds_id or odds_id in source_ids:
            raise ValueError("Blank or duplicated source match ID")
        source_ids.add(odds_id)
        tour = odds.get("tour", "").lower()
        p1_key, p2_key = short_key(odds.get("player1")), short_key(odds.get("player2"))
        played = date.fromisoformat(odds["date_utc"][:10])
        if tour not in {"atp", "wta"} or not p1_key or not p2_key or p1_key == p2_key:
            counts["unusable_tour_or_player_identity"] += 1
            continue
        pair = tuple(sorted((p1_key, p2_key)))
        candidates = [m for m in matches_by_pair.get((tour, pair), [])
                      if m["event_date"] and abs((date.fromisoformat(m["event_date"]) - played).days) <= MAX_DATE_GAP]
        if not candidates:
            counts["no_player_pair_and_date_candidate"] += 1
            continue

        exact_event = [m for m in candidates if norm(m["tourney_name"]) == norm(odds.get("tournament"))]
        use_event_fallback = not exact_event
        if exact_event:
            candidates = exact_event
        score = score_sets(odds.get("score"))
        winner_num = odds.get("winner")
        source_winner_key = p1_key if winner_num == "1" else p2_key if winner_num == "2" else None
        compatible = []
        for match in candidates:
            if not score or source_winner_key is None:
                continue
            # The archive score is always winner/loser-oriented. Reorient it to
            # the source's first/second player order before comparing every set.
            archive_winner_keys = full_keys(match["winner_name"])
            archive_loser_keys = full_keys(match["loser_name"])
            winner_matches_p1 = p1_key in archive_winner_keys
            winner_matches_p2 = p2_key in archive_winner_keys
            loser_matches_p1 = p1_key in archive_loser_keys
            loser_matches_p2 = p2_key in archive_loser_keys
            if (winner_matches_p1 and loser_matches_p2) == (winner_matches_p2 and loser_matches_p1):
                continue
            if (source_winner_key == p1_key) != winner_matches_p1:
                continue
            archive_score = score_sets(match["score"])
            expected = archive_score if winner_matches_p1 else tuple((b, a) for a, b in archive_score)
            if score == expected:
                compatible.append(match)
        if not compatible:
            counts["winner_or_full_set_score_mismatch"] += 1
            continue
        gaps = [abs((date.fromisoformat(m["event_date"]) - played).days) for m in compatible]
        nearest_gap = min(gaps)
        nearest = [m for m, gap in zip(compatible, gaps) if gap == nearest_gap]
        if len(nearest) != 1:
            counts["ambiguous_nearest_archive_match"] += 1
            continue
        match = nearest[0]
        candidates_by_record[match["record_id"]].append({
            "odds": odds, "match": match, "gap": (date.fromisoformat(match["event_date"]) - played).days,
            "fallback": use_event_fallback,
            "source_p1_archive_id": match["winner_id"] if p1_key in full_keys(match["winner_name"]) else match["loser_id"],
            "source_p2_archive_id": match["loser_id"] if p1_key in full_keys(match["winner_name"]) else match["winner_id"],
        })

    aliases = defaultdict(set)
    for candidates in candidates_by_record.values():
        for candidate in candidates:
            for side in (1, 2):
                aliases[(candidate["match"]["tour"], candidate["odds"][f"player{side}_id"])].add(candidate[f"source_p{side}_archive_id"])
    conflicting_aliases = {key for key, values in aliases.items() if len(values) != 1}

    output_fields = [
        "record_id", "tour", "event_date", "match_date_utc", "source_match_id", "source_player1_id",
        "source_player2_id", "source_player1", "source_player2", "source_winner", "source_score",
        "bookmakers", "open_prob_p1", "close_prob_p1", "open_fair_odds_p1", "open_fair_odds_p2",
        "close_fair_odds_p1", "close_fair_odds_p2", "best_close_odds_p1", "best_close_odds_p2",
        "prob_move_pts", "margin_pct", "favorite", "favorite_won", "archive_tournament",
        "archive_winner", "archive_score", "event_start_gap_days", "link_method",
        "archive_winner_id", "archive_loser_id", "model_p1_id", "model_p2_id",
        "source_player1_archive_id", "source_player2_archive_id", "source_status", "archive_outcome", "best_close_quality_flags",
    ]
    link_counts = Counter()
    linked_ids = set()
    model_rows = []
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", newline="", compresslevel=6) as target:
        writer = csv.DictWriter(target, fieldnames=output_fields)
        writer.writeheader()
        for record_id, candidates in sorted(candidates_by_record.items()):
            if len(candidates) > 1:
                link_counts["archive_matches_with_multiple_source_rows"] += 1
            candidates.sort(key=lambda c: abs(c["gap"]))
            nearest_gap = abs(candidates[0]["gap"])
            nearest = [c for c in candidates if abs(c["gap"]) == nearest_gap]
            if len(nearest) != 1:
                link_counts["archive_collision_excluded"] += len(nearest)
                continue
            chosen = nearest[0]
            if any((chosen["match"]["tour"], chosen["odds"][f"player{side}_id"]) in conflicting_aliases for side in (1, 2)):
                link_counts["conflicting_player_alias_excluded"] += 1
                continue
            link_counts["nonnearest_source_rows_excluded"] += len(candidates) - 1
            if chosen["odds"]["match_id"] in linked_ids:
                link_counts["source_collision_excluded"] += 1
                continue
            linked_ids.add(chosen["odds"]["match_id"])
            o, m = chosen["odds"], chosen["match"]
            feature = feature_rows.get(record_id)
            if feature and (o["status"] != "finished" or m["outcome"] != "completed"):
                link_counts["model_excluded_noncompleted_or_status_disagreement"] += 1
                feature = None
            quality_flags = best_close_flags(o)
            link_counts["best_close_pair_flagged"] += bool(quality_flags)
            source_p1_is_model_p1 = None
            if feature:
                if {feature["p1_id"], feature["p2_id"]} != {chosen["source_p1_archive_id"], chosen["source_p2_archive_id"]}:
                    raise ValueError("Linked feature player IDs disagree")
                source_p1_is_model_p1 = chosen["source_p1_archive_id"] == feature["p1_id"]
            # The source's p1/p2 price orientation is retained explicitly;
            # users can align it with model p1/p2 using the matched player IDs.
            method = "player surname+initial pair, <=14-day event-date gap, winner and all set scores match"
            if chosen["fallback"]:
                method += "; tournament title differs"
                link_counts["event_title_fallback"] += 1
            else:
                link_counts["exact_event_title"] += 1
            writer.writerow({
                "record_id": record_id, "tour": m["tour"], "event_date": m["event_date"],
                "match_date_utc": o["date_utc"], "source_match_id": o["match_id"],
                "source_player1_id": o["player1_id"], "source_player2_id": o["player2_id"],
                "source_player1": o["player1"], "source_player2": o["player2"],
                "source_winner": o["winner"], "source_score": o["score"], "bookmakers": o["bookmakers"],
                "open_prob_p1": o["open_prob1"], "close_prob_p1": o["close_prob1"],
                "open_fair_odds_p1": o["open_fair_odds1"], "open_fair_odds_p2": o["open_fair_odds2"],
                "close_fair_odds_p1": o["close_fair_odds1"], "close_fair_odds_p2": o["close_fair_odds2"],
                "best_close_odds_p1": o["best_close_odds1"], "best_close_odds_p2": o["best_close_odds2"],
                "prob_move_pts": o["prob_move_pts"], "margin_pct": o["margin_pct"],
                "favorite": o["favorite"], "favorite_won": o["favorite_won"],
                "archive_tournament": m["tourney_name"], "archive_winner": m["winner_name"],
                "archive_score": m["score"], "event_start_gap_days": chosen["gap"], "link_method": method,
                "archive_winner_id": m["winner_id"], "archive_loser_id": m["loser_id"],
                "model_p1_id": feature["p1_id"] if feature else "",
                "model_p2_id": feature["p2_id"] if feature else "",
                "source_player1_archive_id": chosen["source_p1_archive_id"],
                "source_player2_archive_id": chosen["source_p2_archive_id"],
                "source_status": o["status"], "archive_outcome": m["outcome"],
                "best_close_quality_flags": ";".join(quality_flags),
            })
            link_counts["linked_rows"] += 1
            link_counts["linked_with_model_feature"] += bool(feature)
            if feature:
                flip = not source_p1_is_model_p1
                model_rows.append({
                    **feature,
                    "odds_2025_source_match_id": o["match_id"],
                    "odds_2025_source_player1_id": o["player1_id"],
                    "odds_2025_source_player2_id": o["player2_id"],
                    "odds_2025_source_player1_name": o["player1"],
                    "odds_2025_source_player2_name": o["player2"],
                    "odds_2025_bookmakers": o["bookmakers"],
                    "odds_2025_open_prob_p1": 1 - float(o["open_prob1"]) if flip else o["open_prob1"],
                    "odds_2025_close_prob_p1": 1 - float(o["close_prob1"]) if flip else o["close_prob1"],
                    "odds_2025_open_fair_odds_p1": o["open_fair_odds2"] if flip else o["open_fair_odds1"],
                    "odds_2025_open_fair_odds_p2": o["open_fair_odds1"] if flip else o["open_fair_odds2"],
                    "odds_2025_close_fair_odds_p1": o["close_fair_odds2"] if flip else o["close_fair_odds1"],
                    "odds_2025_close_fair_odds_p2": o["close_fair_odds1"] if flip else o["close_fair_odds2"],
                    "odds_2025_best_close_odds_p1": "" if quality_flags else (o["best_close_odds2"] if flip else o["best_close_odds1"]),
                    "odds_2025_best_close_odds_p2": "" if quality_flags else (o["best_close_odds1"] if flip else o["best_close_odds2"]),
                    "odds_2025_best_close_pair_available": int(not quality_flags),
                    "odds_2025_best_close_quality_flags": ";".join(quality_flags),
                    "odds_2025_prob_move_pts": -float(o["prob_move_pts"]) if flip else o["prob_move_pts"],
                    "odds_2025_margin_pct": o["margin_pct"],
                })

    with gzip.open(MODEL_OUT, "wt", encoding="utf-8", newline="", compresslevel=6) as target:
        writer = csv.DictWriter(target, fieldnames=list(model_rows[0]) if model_rows else [])
        if model_rows:
            writer.writeheader()
            writer.writerows(model_rows)

    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "provider": "minmaxxxer",
            "dataset": "ATP and WTA 2025 closing odds and results",
            "url": "https://huggingface.co/datasets/minmaxxxer/atp-wta-closing-odds-2025",
            "revision": "9d8b6a741f8b26c2386e5556b4b1cc9cf6afd188",
            "license": "CC BY 4.0",
            "attribution": "Data compiled by minmaxxxer from publicly available match and odds information; dataset card CC BY 4.0.",
            "raw_file": "data/odds/sources/atp_wta_2025_closing_odds.csv",
            "raw_sha256": digest(SOURCE),
            "download_url": "https://huggingface.co/datasets/minmaxxxer/atp-wta-closing-odds-2025/resolve/9d8b6a741f8b26c2386e5556b4b1cc9cf6afd188/atp_wta_2025_closing_odds.csv",
            "retrieved_utc_date": "2026-10-26",
            "source_card_file": "data/odds/sources/consensus_2025_UPSTREAM_README.md",
            "source_card_sha256": digest(ROOT / "data/odds/sources/consensus_2025_UPSTREAM_README.md"),
            "raw_rows": len(source_rows),
            "date_range": [min(dates).isoformat(), max(dates).isoformat()],
            "rows_by_tour": dict(Counter(row["tour"] for row in source_rows)),
            "rows_by_status": dict(Counter(row["status"] for row in source_rows)),
            "best_close_pairs_flagged": sum(bool(best_close_flags(row)) for row in source_rows),
        },
        "join_policy": {
            "identity": "tour plus abbreviated surname/initial pair",
            "maximum_event_date_gap_days": MAX_DATE_GAP,
            "requires_winner_and_full_set_score_agreement": True,
            "tiebreak_detail_compared": False,
            "source_player_ids_mapping_to_multiple_archive_ids_excluded": True,
            "exact_normalized_tournament_name_preferred": True,
            "one_to_one_source_and_archive_links": True,
            "ambiguous_matches_excluded": True,
        },
        "counts": dict(sorted((Counter(counts) + Counter(link_counts)).items())),
        "output": {"path": "data/odds/multi_bookmaker_consensus_2025.csv.gz", "sha256": digest(OUT), "bytes": OUT.stat().st_size},
        "model_feature_output": {"path": "data/odds/model_features_with_consensus_odds_2025.csv.gz", "rows": len(model_rows), "sha256": digest(MODEL_OUT), "bytes": MODEL_OUT.stat().st_size},
        "inputs": {"sqlite_sha256": digest(DB), "feature_files": {
            f"data/processed/model_features_by_year/model_features_{year}.csv.gz": digest(ROOT / f"data/processed/model_features_by_year/model_features_{year}.csv.gz")
            for year in (2024, 2025)}},
        "model_rows_by_tour": dict(Counter(row["tour"] for row in model_rows)),
        "model_rows_with_best_close_pair": sum(row["odds_2025_best_close_pair_available"] for row in model_rows),
        "market_timing": "Opening/closing labels are publisher-reported; quote timestamps are unavailable and have not been independently verified.",
        "best_close_filter": "Retain raw values; blank both best-close prices in model export when either price is invalid or exceeds twice its corresponding fair closing odds. This heuristic does not establish executability or pre-match timing.",
        "conflicting_source_player_ids": len(conflicting_aliases),
        "limitations": [
            "The source is a 2025 sample and does not extend the repository's historical odds start date.",
            "Only source matches with an unambiguous archive candidate and exact winner/set-score agreement are linked.",
            "The linked odds crosswalk preserves source player1/player2 order; the separate model feature export reorients prices to p1/p2.",
        ],
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report["counts"], indent=2))
    print(json.dumps(report["output"], indent=2))


if __name__ == "__main__":
    main()
