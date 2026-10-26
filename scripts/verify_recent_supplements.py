"""Validate append-only recent features, rankings, profiles, and their reports."""
import csv
import gzip
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/odds"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_gzip_csv(name: str) -> list[dict[str, str]]:
    with gzip.open(DATA / name, "rt", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def unique_by_record(rows: list[dict[str, str]], label: str) -> dict[str, dict[str, str]]:
    result = {}
    for row in rows:
        key = row.get("record_id", "")
        if not key or key in result:
            raise ValueError(f"{label}: blank or duplicate record_id {key!r}")
        result[key] = row
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> None:
    feature_path = DATA / "recent_model_features.csv.gz"
    rank_path = DATA / "recent_ranking_fallbacks.csv.gz"
    profile_path = DATA / "recent_player_profiles.csv.gz"
    feature_report = json.loads((DATA / "recent_model_features_report.json").read_text(encoding="utf-8"))
    rank_report = json.loads((DATA / "recent_ranking_fallbacks_report.json").read_text(encoding="utf-8"))
    profile_report = json.loads((DATA / "recent_player_profiles_report.json").read_text(encoding="utf-8"))

    features = unique_by_record(read_gzip_csv(feature_path.name), "recent features")
    rankings = unique_by_record(read_gzip_csv(rank_path.name), "recent rankings")
    profiles = unique_by_record(read_gzip_csv(profile_path.name), "recent profiles")
    require(len(features) == feature_report["total_rows"], "recent feature row count differs from report")
    require(sha256(feature_path) == feature_report["sha256"], "recent feature checksum differs from report")
    require(len(rankings) == rank_report["total_rows_with_fallbacks"], "recent ranking row count differs from report")
    require(sha256(rank_path) == rank_report["sha256"], "recent ranking checksum differs from report")
    require(len(profiles) == profile_report["recent_feature_rows"], "recent profile row count differs from report")
    require(sha256(profile_path) == profile_report["profile_supplement_sha256"], "recent profile checksum differs from report")

    today = datetime.now(timezone.utc).date()
    for record_id, row in features.items():
        event_day = date.fromisoformat(row["event_date"])
        cutoff = date.fromisoformat(row["history_cutoff_exclusive"])
        require(event_day <= today, f"future-dated feature row {record_id}")
        require(cutoff == event_day - timedelta(days=28), f"incorrect history embargo for {record_id}")
        require(row["p1_won"] in {"0", "1"}, f"invalid target label for {record_id}")
        for side in ("p1", "p2"):
            latest = row.get(f"{side}_history_latest_date", "")
            require(not latest or date.fromisoformat(latest) < cutoff,
                    f"post-cutoff history leaked into {record_id} {side}")

    for label, supplement in (("rank", rankings), ("profile", profiles)):
        for record_id, row in supplement.items():
            require(record_id in features, f"{label} supplement has orphan record_id {record_id}")
            base = features[record_id]
            for field in ("tour", "event_date", "p1_id", "p2_id"):
                require(row.get(field) == base.get(field), f"{label} supplement key mismatch for {record_id}: {field}")

    rank_fills = 0
    for record_id, row in rankings.items():
        event_day = date.fromisoformat(row["event_date"])
        for side in ("p1", "p2"):
            snapshot = row.get(f"{side}_rank_snapshot_date", "")
            age = row.get(f"{side}_rank_age_days", "")
            rank = row.get(f"{side}_rank_fallback", "")
            points = row.get(f"{side}_rank_points_fallback", "")
            if rank or points:
                rank_fills += bool(rank)
                require(snapshot and age, f"rank value missing provenance for {record_id} {side}")
                snapshot_day = date.fromisoformat(snapshot)
                delta = (event_day - snapshot_day).days
                require(1 <= delta <= 90 and int(age) == delta,
                        f"invalid ranking snapshot date/age for {record_id} {side}")
    require(rank_fills == rank_report["rank_fills"], "rank fill count differs from report")

    profile_values = {"age": 0, "height": 0, "hand": 0, "rows": 0}
    rows_with_profile = 0
    for record_id, row in profiles.items():
        event_day = date.fromisoformat(row["event_date"])
        has_value = False
        for side in ("p1", "p2"):
            age = row.get(f"{side}_age_fallback", "")
            birth = row.get(f"{side}_birth_date", "")
            if age:
                require(birth, f"age has no birth-date provenance for {record_id} {side}")
                expected = round((event_day - date.fromisoformat(birth)).days / 365.2425, 1)
                require(float(age) == expected, f"age does not match birth date for {record_id} {side}")
                require(row.get(f"{side}_birth_date_source"), f"birth date source missing for {record_id} {side}")
                profile_values["age"] += 1
                has_value = True
            height = row.get(f"{side}_ht_fallback", "")
            if height:
                require(row.get(f"{side}_height_source"), f"height source missing for {record_id} {side}")
                require(130 <= float(height) <= 230, f"implausible height for {record_id} {side}")
                profile_values["height"] += 1
                has_value = True
            hand = row.get(f"{side}_hand_fallback", "")
            if hand:
                require(row.get(f"{side}_hand_source"), f"hand source missing for {record_id} {side}")
                profile_values["hand"] += 1
                has_value = True
        rows_with_profile += has_value
    profile_values["rows"] = rows_with_profile
    require(profile_values == profile_report["field_values"], "profile field counts differ from report")
    require(len(profiles) == profile_report["rows_with_profile_data"], "profile row count differs from report")
    print(f"Verified {len(features):,} recent feature rows, {len(rankings):,} ranking supplements, and {len(profiles):,} profile supplements; temporal guards and hashes match.")


if __name__ == "__main__":
    main()
