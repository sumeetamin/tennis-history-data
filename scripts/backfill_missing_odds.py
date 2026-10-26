"""Append newly published settled Valuebetennis matches from every available season."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path

from odds_quality import is_settled

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://www.valuebetennis.com/datasets"
OUTPUT = ROOT / "data/odds/atp_wta_match_odds.csv"
MANIFEST = ROOT / "data/odds/valuebetennis_manifest.json"
FIRST_YEAR = 2021


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_year(year: int, target: Path) -> bool:
    url = f"{BASE_URL}/valuebetennis-matchs-{year}.csv"
    request = urllib.request.Request(url, headers={"User-Agent": "tennis-history-data/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response, target.open("wb") as out:
            out.write(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Read already downloaded season CSVs")
    parser.add_argument("--through-year", type=int, default=datetime.now(timezone.utc).year)
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    args = parser.parse_args()
    if not OUTPUT.is_file() or not MANIFEST.is_file():
        raise SystemExit("Initial odds export missing; run scripts/fetch_valuebetennis_odds.py first")
    if args.through_year < FIRST_YEAR or args.through_year > args.today.year:
        parser.error("--through-year must be between 2021 and the current year")

    with OUTPUT.open("r", encoding="utf-8", newline="") as stream:
        existing_reader = csv.DictReader(stream)
        columns = existing_reader.fieldnames
        if not columns or "match_id" not in columns:
            raise ValueError("Odds export has no match_id column")
        existing_ids: set[str] = set()
        rows_by_year: Counter[str] = Counter()
        rows_by_tour: Counter[str] = Counter()
        duplicate_ids = 0
        existing_rows = 0
        for row in existing_reader:
            existing_rows += 1
            match_id = row.get("match_id") or ""
            if match_id in existing_ids:
                duplicate_ids += 1
            existing_ids.add(match_id)
            year = (row.get("date") or "")[:4]
            tour = (row.get("genre") or "").lower()
            if year.isdigit():
                rows_by_year[year] += 1
            if tour in {"atp", "wta"}:
                rows_by_tour[tour] += 1

    appended: list[dict[str, str]] = []
    appended_ids: set[str] = set()
    source_hashes: dict[str, str] = {}
    missing_seasons: list[int] = []
    invalid_or_unsettled = 0
    temp_context = tempfile.TemporaryDirectory(prefix="tennis-all-season-backfill-") if args.source_dir is None else nullcontext(args.source_dir)
    with temp_context as temp:
        temp_path = Path(temp)
        for year in range(FIRST_YEAR, args.through_year + 1):
            path = temp_path / f"valuebetennis-matchs-{year}.csv"
            if args.source_dir is None:
                if not fetch_year(year, path):
                    missing_seasons.append(year)
                    continue
            elif not path.is_file():
                missing_seasons.append(year)
                continue
            source_hashes[str(year)] = sha256(path)
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, delimiter=";")
                if reader.fieldnames != columns:
                    raise ValueError(f"Column mismatch in source season {year}")
                for row in reader:
                    match_id = row.get("match_id") or ""
                    if not match_id or match_id in existing_ids or match_id in appended_ids:
                        continue
                    tour = (row.get("genre") or "").lower()
                    if tour not in {"atp", "wta"}:
                        continue
                    try:
                        match_day = datetime.strptime(row["date"], "%Y-%m-%d %H:%M:%S").date()
                    except (KeyError, ValueError):
                        invalid_or_unsettled += 1
                        continue
                    if match_day > args.today or not is_settled(row):
                        invalid_or_unsettled += 1
                        continue
                    appended.append(row)
                    appended_ids.add(match_id)
                    rows_by_year[str(year)] += 1
                    rows_by_tour[tour] += 1

    # Append mode preserves all prior CSV bytes and rows exactly.
    if appended:
        with OUTPUT.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            for row in appended:
                writer.writerow(row)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest.update({
        "rows": existing_rows + len(appended),
        "rows_by_tour": dict(sorted(rows_by_tour.items())),
        "rows_by_year": dict(sorted(rows_by_year.items())),
        "duplicate_match_ids_in_file": duplicate_ids,
        "combined_sha256": sha256(OUTPUT),
        "combined_bytes": OUTPUT.stat().st_size,
        "last_full_history_backfill": {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "source_years_checked": sorted(source_hashes, key=int),
            "source_year_sha256": source_hashes,
            "source_seasons_not_available": missing_seasons,
            "new_settled_rows_appended": len(appended),
            "new_rows_by_tour": dict(sorted(Counter((r.get("genre") or "").lower() for r in appended).items())),
            "unsettled_future_or_invalid_rows_skipped": invalid_or_unsettled,
            "existing_rows_rewritten": 0,
            "policy": "Append unseen settled match IDs from all available seasons; never revise existing rows.",
        },
    })
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["last_full_history_backfill"], indent=2))
    print(f"Total odds/results rows: {manifest['rows']:,}; SHA-256: {manifest['combined_sha256']}")


if __name__ == "__main__":
    main()
