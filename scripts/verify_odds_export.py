"""Check the append-only odds CSV against its committed manifest."""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data/odds/atp_wta_match_odds.csv"
MANIFEST_PATH = ROOT / "data/odds/valuebetennis_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    ids: set[str] = set()
    tours: Counter[str] = Counter()
    years: Counter[str] = Counter()
    duplicates = 0
    rows = 0
    with CSV_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"match_id", "genre", "date", "vainqueur_id", "score"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"Odds CSV is missing required columns: {sorted(required)}")
        for row in reader:
            rows += 1
            match_id = (row.get("match_id") or "").strip()
            tour = (row.get("genre") or "").strip().lower()
            day = (row.get("date") or "")[:10]
            if not match_id:
                raise ValueError(f"Blank match_id at data row {rows}")
            if match_id in ids:
                duplicates += 1
            ids.add(match_id)
            if tour not in {"atp", "wta"}:
                raise ValueError(f"Invalid tour at data row {rows}: {tour!r}")
            tours[tour] += 1
            if len(day) != 10 or day[4] != "-" or day[7] != "-":
                raise ValueError(f"Invalid match date at data row {rows}: {day!r}")
            years[day[:4]] += 1

    expected = {
        "rows": rows == manifest.get("rows"),
        "tour counts": dict(sorted(tours.items())) == manifest.get("rows_by_tour"),
        "year counts": dict(sorted(years.items())) == manifest.get("rows_by_year"),
        "duplicate count": duplicates == manifest.get("duplicate_match_ids_in_file"),
        "checksum": sha256(CSV_PATH) == manifest.get("combined_sha256"),
        "byte size": CSV_PATH.stat().st_size == manifest.get("combined_bytes"),
    }
    failed = [name for name, ok in expected.items() if not ok]
    if failed:
        raise SystemExit("Odds export verification failed: " + ", ".join(failed))
    if duplicates:
        raise SystemExit(f"Odds export contains {duplicates} duplicate match IDs")
    print(f"Verified {rows:,} odds rows; tours={dict(tours)}; years={dict(sorted(years.items()))}; SHA-256={manifest['combined_sha256']}")


if __name__ == "__main__":
    main()
