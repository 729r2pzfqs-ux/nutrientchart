#!/usr/bin/env python3
"""Download the USDA FoodData Central bulk CSV archives used by the site into data/source/.

    python3 tools/fetch_usda.py

Releases are pinned by file name so a rebuild reproduces the same numbers. SR Legacy (April 2018) is the
final release of that data type and will never change; Foundation Foods is refreshed each April and October
(update FOUNDATION when a new release is adopted and bump DATA_UPDATED in build.py).
Source: https://fdc.nal.usda.gov/download-datasets/  (public domain, CC0 1.0).
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://fdc.nal.usda.gov/fdc-datasets/"
SR_LEGACY = "FoodData_Central_sr_legacy_food_csv_2018-04.zip"
FOUNDATION = "FoodData_Central_foundation_food_csv_2026-04-30.zip"
OUT = Path(__file__).resolve().parent.parent / "data" / "source"


def fetch(name: str) -> None:
    dest = OUT / name
    if dest.exists() and dest.stat().st_size > 100_000:
        print(f"have {name} ({dest.stat().st_size // 1024} KB)")
        return
    req = urllib.request.Request(BASE + name, headers={"User-Agent": "Mozilla/5.0 nutrientchart-build"})
    print(f"downloading {name} ...")
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 16):
            f.write(chunk)
    print(f"saved {dest} ({dest.stat().st_size // 1024} KB)")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in (SR_LEGACY, FOUNDATION):
        fetch(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
