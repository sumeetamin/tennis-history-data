"""Build a joined, audited view of recent features and their provider metadata."""
import csv
import gzip
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/odds"
FEATURES = DATA / "recent_model_features.csv.gz"
SOURCE = DATA / "atp_wta_match_odds.csv"
RANKS = DATA / "recent_ranking_fallbacks.csv.gz"
PROFILES = DATA / "recent_player_profiles.csv.gz"
FEATURE_REPORT = DATA / "recent_model_features_report.json"
ALL_OUT = DATA / "recent_model_features_enriched.csv.gz"
MAIN_OUT = DATA / "recent_main_tour_event_features.csv.gz"
LOWER_OUT = DATA / "recent_lower_tier_event_features.csv.gz"
REPORT_OUT = DATA / "recent_features_enrichment_report.json"
MAIN_LEVELS = {"main_tour", "masters", "grand_slam"}
LOWER_LEVELS = {"challenger", "itf"}

EXTRA = [
    "source_category", "competition_group", "is_main_tour_event",
    "source_round_code", "round_name", "round_mapping_status",
    "source_match_datetime_utc", "odds_opening_pair_available",
    "odds_last_pre_match_pair_available", "odds_quote_timestamp_utc",
    "odds_timestamp_verified", "odds_timing_basis",
    "odds_last_pre_match_p1_decimal", "odds_last_pre_match_p2_decimal",
    "p1_rank_source", "p2_rank_source", "p1_rank_snapshot_date",
    "p2_rank_snapshot_date", "p1_rank_snapshot_age_days",
    "p2_rank_snapshot_age_days", "p1_birth_date", "p2_birth_date",
    "p1_birth_date_source", "p2_birth_date_source",
    "p1_height_source", "p2_height_source", "p1_hand_source", "p2_hand_source",
]


def read_rows(path, compressed=False):
    opener = gzip.open if compressed else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def keyed_rows(path):
    rows = read_rows(path, compressed=True)
    keyed = {}
    for row in rows:
        key = row.get("record_id", "")
        if not key or key in keyed:
            raise ValueError(f"Blank or duplicate record_id in {path}: {key!r}")
        keyed[key] = row
    return keyed


def present(value):
    return value is not None and str(value).strip() != ""


def positive(value):
    try:
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError):
        return None


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def level(category):
    c = normalize(category)
    if "grand chelem" in c or "grand slam" in c:
        return "grand_slam"
    if "master" in c or "1000" in c:
        return "masters"
    if "main tour" in c or c in {"tour", "principal"}:
        return "main_tour"
    if "challenger" in c or "125" in c:
        return "challenger"
    if "itf" in c or "futures" in c:
        return "itf"
    return "unknown"


def round_code(value):
    try:
        n = float(value)
        return str(int(n)) if math.isfinite(n) and n.is_integer() and 0 <= n <= 12 else ""
    except (TypeError, ValueError):
        return ""


def utc(value):
    value = str(value or "").strip()
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def merge(feature, raw, rank, profile):
    row = dict(feature)
    category = raw.get("categorie", "") if raw else ""
    group = level(category)
    code = round_code(raw.get("tour")) if raw else ""
    row.update({
        "source_category": category,
        "competition_group": group,
        "is_main_tour_event": str(group in MAIN_LEVELS).lower(),
        "source_round_code": code,
        "round_name": "Pre-qualifications" if code == "0" else "Final" if code == "12" else "",
        "round_mapping_status": (
            "source documents code 0 as pre-qualifications" if code == "0" else
            "source documents code 12 as final" if code == "12" else
            "intermediate numeric code retained; round name not documented" if code else
            "round code unavailable"
        ),
        "source_match_datetime_utc": utc(raw.get("date")) if raw else "",
        "odds_quote_timestamp_utc": "",
        "odds_timestamp_verified": "false",
        "odds_timing_basis": "provider-labelled opening/last pre-match; exact quote timestamps unavailable",
    })
    if group != "unknown" and not present(row.get("tourney_level")):
        row["tourney_level"] = group

    opening = [positive(row.get("odds_open_p1_decimal")), positive(row.get("odds_open_p2_decimal"))]
    last = [positive(row.get("odds_close_p1_decimal")), positive(row.get("odds_close_p2_decimal"))]
    row["odds_opening_pair_available"] = str(all(v is not None for v in opening)).lower()
    row["odds_last_pre_match_pair_available"] = str(all(v is not None for v in last)).lower()
    row["odds_last_pre_match_p1_decimal"] = last[0] or ""
    row["odds_last_pre_match_p2_decimal"] = last[1] or ""

    for side in ("p1", "p2"):
        rnk = positive(row.get(f"{side}_rank"))
        if rnk is None and rank:
            rnk = positive(rank.get(f"{side}_rank_fallback"))
            row[f"{side}_rank_snapshot_date"] = rank.get(f"{side}_rank_snapshot_date", "")
            row[f"{side}_rank_snapshot_age_days"] = rank.get(f"{side}_rank_age_days", "")
        if rnk is not None:
            row[f"{side}_rank"] = int(rnk) if rnk.is_integer() else rnk
        row[f"{side}_rank_source"] = (
            "recent feature source" if positive(feature.get(f"{side}_rank")) is not None else
            "prior weekly ranking snapshot" if rnk is not None else "missing"
        )

        points = positive(row.get(f"{side}_rank_points"))
        if points is None and rank:
            points = positive(rank.get(f"{side}_rank_points_fallback"))
            if points is not None and not present(row.get(f"{side}_rank_snapshot_date")):
                row[f"{side}_rank_snapshot_date"] = rank.get(f"{side}_rank_snapshot_date", "")
                row[f"{side}_rank_snapshot_age_days"] = rank.get(f"{side}_rank_age_days", "")
        if points is not None:
            row[f"{side}_rank_points"] = int(points) if points.is_integer() else points

        if profile:
            for target, supplement in (
                (f"{side}_age", f"{side}_age_fallback"),
                (f"{side}_ht", f"{side}_ht_fallback"),
                (f"{side}_hand", f"{side}_hand_fallback"),
            ):
                if not present(row.get(target)) and present(profile.get(supplement)):
                    row[target] = profile[supplement]
            for field in ("birth_date", "birth_date_source", "height_source", "hand_source"):
                row[f"{side}_{field}"] = profile.get(f"{side}_{field}", "")
        else:
            for field in ("birth_date", "birth_date_source", "height_source", "hand_source"):
                row[f"{side}_{field}"] = ""

    for key in ("rank", "rank_points", "age", "ht"):
        a, b = positive(row.get(f"p1_{key}")), positive(row.get(f"p2_{key}"))
        diff_key = f"{key}_diff"
        row[diff_key] = a - b if a is not None and b is not None else ""
    return row


def summarize(rows, source, feature_report):
    groups = {
        "tour": defaultdict(list), "season": defaultdict(list),
        "event_level": defaultdict(list), "surface": defaultdict(list),
        "round_code": defaultdict(list),
    }
    for row in rows:
        for dim, key in (
            ("tour", row.get("tour") or "unknown"),
            ("season", (row.get("event_date") or "")[:4] or "unknown"),
            ("event_level", row.get("competition_group") or "unknown"),
            ("surface", row.get("surface") or "unknown"),
            ("round_code", row.get("source_round_code") or "unknown"),
        ):
            groups[dim][key].append(row)

    fields = (
        "p1_rank", "p2_rank", "p1_rank_points", "p2_rank_points",
        "p1_age", "p2_age", "p1_ht", "p2_ht", "p1_hand", "p2_hand",
        "prior_matches", "surface_prior_matches", "recent365_matches",
    )

    def missingness(part):
        n = len(part)
        return {f: {
            "available": sum(present(r.get(f)) for r in part),
            "missing": sum(not present(r.get(f)) for r in part),
            "coverage_pct": round(100 * sum(present(r.get(f)) for r in part) / n, 2) if n else 0,
        } for f in fields}

    def pair_count(left, right):
        return sum(positive(r.get(left)) is not None and positive(r.get(right)) is not None for r in rows)

    return {
        "rows": len(rows),
        "date_range": [min((r["event_date"] for r in rows), default=None),
                       max((r["event_date"] for r in rows), default=None)],
        "strict_identity_unverified_candidates_excluded": feature_report.get("skipped_unverified_identity"),
        "source_join_missing_rows": sum(r["record_id"][3:] not in source for r in rows),
        "counts_by_tour": {k: len(v) for k, v in sorted(groups["tour"].items())},
        "counts_by_season": {k: len(v) for k, v in sorted(groups["season"].items())},
        "counts_by_event_level": {k: len(v) for k, v in sorted(groups["event_level"].items())},
        "counts_by_surface": {k: len(v) for k, v in sorted(groups["surface"].items())},
        "counts_by_source_round_code": {k: len(v) for k, v in sorted(groups["round_code"].items())},
        "missingness_by_tour": {k: missingness(v) for k, v in sorted(groups["tour"].items())},
        "field_missingness": missingness(rows),
        "odds": {
            "opening_pair_rows": pair_count("odds_open_p1_decimal", "odds_open_p2_decimal"),
            "last_pre_match_pair_rows": pair_count("odds_close_p1_decimal", "odds_close_p2_decimal"),
            "quote_timestamp_rows": 0,
            "timestamp_verified_rows": 0,
            "timing_note": "Prices have provider opening/last-pre-match labels but no verifiable quote timestamps."
        },
        "identity_target": {
            "unique_record_ids": len({r.get("record_id") for r in rows}),
            "duplicate_record_ids": len(rows) - len({r.get("record_id") for r in rows}),
            "p1_won_counts": dict(Counter(r.get("p1_won", "") for r in rows)),
        },
        "round_code_note": "Source documents code 0 as pre-qualifications and code 12 as final. Intermediate codes are preserved, not guessed into round names.",
        "main_tour_subset_note": "Main Tour, Masters, and Grand Slam event categories; qualifying-stage rows are not independently removed.",
        "data_sources": {
            "results_odds": "Valuebetennis, https://www.valuebetennis.com/donnees.htm, CC BY 4.0",
            "ranking_fallbacks": "Prior weekly Sackmann ranking snapshots; strictly before match date and at most 90 days old",
            "player_profiles": "Sackmann roster plus Wikidata CC0 supplement; height is not historical",
            "identity": "Strict unique provider-player-ID/name crosswalk",
        },
    }


def write_gzip(path, rows, fields):
    with gzip.open(path, "wt", encoding="utf-8", newline="", compresslevel=6) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    inputs = (FEATURES, SOURCE, RANKS, PROFILES, FEATURE_REPORT)
    missing = [p.as_posix() for p in inputs if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing recent-data inputs: {missing}")

    features = read_rows(FEATURES, compressed=True)
    raw = read_rows(SOURCE)
    source = {}
    for row in raw:
        match_id = row.get("match_id", "")
        if not match_id or match_id in source:
            raise ValueError(f"Blank or duplicate Valuebetennis match_id: {match_id!r}")
        source[match_id] = row
    ranks, profiles = keyed_rows(RANKS), keyed_rows(PROFILES)
    feature_report = json.loads(FEATURE_REPORT.read_text(encoding="utf-8"))

    seen, enriched = set(), []
    for feature in features:
        record_id = feature.get("record_id", "")
        if not record_id or record_id in seen or not record_id.startswith("vb:"):
            raise ValueError(f"Blank, duplicate, or unexpected recent record_id: {record_id!r}")
        seen.add(record_id)
        enriched.append(merge(feature, source.get(record_id[3:]),
                              ranks.get(record_id), profiles.get(record_id)))

    fields = list(dict.fromkeys([*features[0].keys(), *EXTRA]))
    write_gzip(ALL_OUT, enriched, fields)
    main_rows = [r for r in enriched if r["competition_group"] in MAIN_LEVELS]
    lower_rows = [r for r in enriched if r["competition_group"] in LOWER_LEVELS]
    write_gzip(MAIN_OUT, main_rows, fields)
    write_gzip(LOWER_OUT, lower_rows, fields)

    report = summarize(enriched, source, feature_report)
    report["subsets"] = {
        "all_levels": {"rows": len(enriched), "file": ALL_OUT.relative_to(ROOT).as_posix()},
        "main_tour_event_levels": {
            "rows": len(main_rows), "file": MAIN_OUT.relative_to(ROOT).as_posix(),
            "definition": "Main Tour, Masters, and Grand Slam event categories; qualifying stages remain identifiable only by raw round code."
        },
        "challenger_itf_event_levels": {"rows": len(lower_rows), "file": LOWER_OUT.relative_to(ROOT).as_posix()},
        "unknown_event_level_rows": sum(r["competition_group"] == "unknown" for r in enriched),
    }
    report["files"] = {}
    for path, count in ((ALL_OUT, len(enriched)), (MAIN_OUT, len(main_rows)), (LOWER_OUT, len(lower_rows))):
        report["files"][path.relative_to(ROOT).as_posix()] = {
            "rows": count, "bytes": path.stat().st_size, "sha256": sha(path)
        }
    report["inputs"] = {p.relative_to(ROOT).as_posix(): sha(p) for p in inputs[:-1]}
    REPORT_OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(enriched), "main_tour_event_rows": len(main_rows),
                      "challenger_itf_rows": len(lower_rows),
                      "report": REPORT_OUT.relative_to(ROOT).as_posix()}, indent=2))


if __name__ == "__main__":
    main()
