"""Download and combine Valuebetennis' CC BY 4.0 ATP/WTA odds CSVs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import urllib.request
from contextlib import nullcontext
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://www.valuebetennis.com/datasets"
FIRST_YEAR = 2021
OUTPUT = ROOT / "data/odds/atp_wta_match_odds.csv"
MANIFEST = ROOT / "data/odds/valuebetennis_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, help="Use already-downloaded yearly CSVs from this folder")
    args = parser.parse_args()

    years = range(FIRST_YEAR, datetime.now(timezone.utc).year + 1)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    downloads: list[dict[str, object]] = []
    tour_counts: Counter[str] = Counter()
    match_ids: set[str] = set()
    duplicate_match_ids = 0
    total_rows = 0
    fieldnames: list[str] | None = None

    temp_context = tempfile.TemporaryDirectory(prefix="valuebetennis-odds-") if args.source_dir is None else nullcontext(str(args.source_dir))
    with temp_context as temp:
        source_dir = args.source_dir or Path(temp)
        if args.source_dir is None:
            source_dir.mkdir(parents=True, exist_ok=True)
        with OUTPUT.open("w", encoding="utf-8", newline="") as combined:
            writer = None
            for year in years:
                filename = f"valuebetennis-matchs-{year}.csv"
                source = source_dir / filename
                if args.source_dir is None:
                    request = urllib.request.Request(
                        f"{BASE_URL}/{filename}", headers={"User-Agent": "tennis-history-data/1.0"}
                    )
                    with urllib.request.urlopen(request, timeout=60) as response, source.open("wb") as target:
                        target.write(response.read())

                year_rows = 0
                with source.open("r", encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream, delimiter=";")
                    if not reader.fieldnames:
                        raise ValueError(f"Missing CSV header: {source}")
                    if fieldnames is None:
                        fieldnames = reader.fieldnames
                        writer = csv.DictWriter(combined, fieldnames=fieldnames)
                        writer.writeheader()
                    elif reader.fieldnames != fieldnames:
                        raise ValueError(f"Column mismatch in {source}")
                    for row in reader:
                        tour = (row.get("genre") or "").lower()
                        if tour not in {"atp", "wta"}:
                            raise ValueError(f"Unexpected tour {tour!r} in {source}")
                        match_id = row.get("match_id") or ""
                        if match_id in match_ids:
                            duplicate_match_ids += 1
                        match_ids.add(match_id)
                        assert writer is not None
                        writer.writerow(row)
                        tour_counts[tour] += 1
                        year_rows += 1
                total_rows += year_rows
                downloads.append({"year": year, "rows": year_rows, "sha256": sha256(source)})

    manifest = {
        "source": "Valuebetennis, Résultats et cotes de tennis depuis 2021",
        "source_url": "https://www.valuebetennis.com/donnees.htm",
        "license": "CC BY 4.0",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "combined_file": OUTPUT.relative_to(ROOT).as_posix(),
        "delimiter": ",",
        "rows": total_rows,
        "rows_by_tour": dict(sorted(tour_counts.items())),
        "rows_by_year": {str(item["year"]): item["rows"] for item in downloads},
        "duplicate_match_ids_in_file": duplicate_match_ids,
        "combined_sha256": sha256(OUTPUT),
        "combined_bytes": OUTPUT.stat().st_size,
        "year_files": downloads,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {total_rows:,} rows to {OUTPUT}")
    print(f"Rows by tour: {dict(tour_counts)}")


if __name__ == "__main__":
    main()
