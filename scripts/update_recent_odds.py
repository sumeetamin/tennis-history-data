"""Append only missing settled ATP/WTA singles matches from the last N days."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import urllib.error
import urllib.request
from contextlib import nullcontext
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from odds_quality import is_settled, settlement_status

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://www.valuebetennis.com/datasets"
OUTPUT = ROOT / "data/odds/atp_wta_match_odds.csv"
MANIFEST = ROOT / "data/odds/valuebetennis_manifest.json"


def fetch_year(year: int, destination: Path) -> bool:
    filename = f"valuebetennis-matchs-{year}.csv"
    request = urllib.request.Request(
        f"{BASE_URL}/{filename}", headers={"User-Agent": "tennis-history-data/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as target:
            target.write(response.read())
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    return True


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--source-dir", type=Path, help="Use already-downloaded provider season CSVs")
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date(),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.lookback_days < 1 or args.lookback_days > 366:
        parser.error("--lookback-days must be between 1 and 366")
    if not OUTPUT.is_file() or not MANIFEST.is_file():
        raise SystemExit("Initial odds export missing; run scripts/fetch_valuebetennis_odds.py first")

    with OUTPUT.open("r", encoding="utf-8", newline="") as existing_file:
        existing_reader = csv.DictReader(existing_file)
        fieldnames = existing_reader.fieldnames
        if not fieldnames or "match_id" not in fieldnames:
            raise ValueError("Existing odds CSV has no match_id column")
        existing_ids: set[str] = set()
        rows_by_tour: Counter[str] = Counter()
        rows_by_year: Counter[str] = Counter()
        duplicate_ids = 0
        existing_rows = 0
        for row in existing_reader:
            existing_rows += 1
            match_id = row.get("match_id") or ""
            if match_id:
                if match_id in existing_ids:
                    duplicate_ids += 1
                existing_ids.add(match_id)
            tour = (row.get("genre") or "").lower()
            if tour:
                rows_by_tour[tour] += 1
            year = (row.get("date") or "")[:4]
            if year.isdigit():
                rows_by_year[year] += 1

    start_date = args.today - timedelta(days=args.lookback_days)
    years = range(start_date.year, args.today.year + 1)
    new_rows: list[dict[str, str]] = []
    new_ids: set[str] = set()
    by_tour: Counter[str] = Counter()
    checked_source_rows = 0
    unsettled_rows_skipped = 0
    source_hashes: dict[str, str] = {}

    temp_context = tempfile.TemporaryDirectory(prefix="recent-tennis-odds-") if args.source_dir is None else nullcontext(args.source_dir)
    unavailable_years: list[int] = []
    with temp_context as temp:
        for year in years:
            source = Path(temp) / f"valuebetennis-matchs-{year}.csv"
            if args.source_dir is None:
                if not fetch_year(year, source):
                    unavailable_years.append(year)
                    continue
            elif not source.is_file():
                unavailable_years.append(year)
                continue
            source_hashes[str(year)] = file_sha256(source)
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream, delimiter=";")
                if reader.fieldnames != fieldnames:
                    raise ValueError(f"Column mismatch in source year {year}")
                for row in reader:
                    checked_source_rows += 1
                    match_id = row.get("match_id") or ""
                    if not match_id or match_id in existing_ids or match_id in new_ids:
                        continue
                    tour = (row.get("genre") or "").lower()
                    if tour not in {"atp", "wta"}:
                        continue
                    try:
                        match_day = datetime.strptime(row["date"], "%Y-%m-%d %H:%M:%S").date()
                    except (KeyError, ValueError):
                        continue
                    # Include settled matches in the rolling backfill window. Future-dated
                    # and unfinished rows are ignored even if a source export contains them.
                    if not start_date <= match_day <= args.today:
                        continue
                    if (not row.get("vainqueur_id")
                            or row.get("vainqueur_id") not in {row.get("joueur1_id"), row.get("joueur2_id")}
                            or not row.get("score") or not is_settled(row)):
                        unsettled_rows_skipped += 1
                        continue
                    new_rows.append(row)
                    new_ids.add(match_id)
                    by_tour[tour] += 1

    if new_rows:
        # Append mode preserves every existing CSV byte and row. Existing match IDs are never revised.
        with OUTPUT.open("a", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            for row in new_rows:
                writer.writerow(row)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["rows"] = existing_rows + len(new_rows)
    counts = Counter(rows_by_tour)
    counts.update(by_tour)
    manifest["rows_by_tour"] = dict(sorted(counts.items()))
    for row in new_rows:
        year = (row.get("date") or "")[:4]
        if year.isdigit():
            rows_by_year[year] += 1
    manifest["rows_by_year"] = dict(sorted(rows_by_year.items()))
    manifest["duplicate_match_ids_in_file"] = duplicate_ids
    manifest["combined_sha256"] = file_sha256(OUTPUT)
    manifest["combined_bytes"] = OUTPUT.stat().st_size
    if new_rows:
        manifest["last_incremental_update_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["last_incremental_window"] = {
            "from": start_date.isoformat(),
            "through": args.today.isoformat(),
            "source_rows_checked": checked_source_rows,
            "source_year_sha256": source_hashes,
            "source_years_not_yet_available": unavailable_years,
            "unsettled_rows_skipped": unsettled_rows_skipped,
            "new_rows_appended": len(new_rows),
            "new_rows_by_tour": dict(sorted(by_tour.items())),
        }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if not new_rows:
        print(f"No missing settled matches in {start_date} through {args.today}; refreshed manifest counts and checksum only.")
        print(f"Skipped {unsettled_rows_skipped:,} unfinished or invalid result rows inside the lookback window")
        if unavailable_years:
            print(f"Source season files not available yet: {unavailable_years}")
        return
    print(f"Appended {len(new_rows):,} missing matches: {dict(by_tour)}")
    print(f"Skipped {unsettled_rows_skipped:,} unfinished or invalid result rows inside the lookback window")
    print(f"Verified manifest: {manifest['rows']:,} rows; {duplicate_ids} duplicate IDs; SHA-256 {manifest['combined_sha256']}")


if __name__ == "__main__":
    main()
