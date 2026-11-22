#!/usr/bin/env python3
"""Build the extension's on-device 'well-known sites' skip list from the Tranco top sites ranking.

    python scripts/make_skiplist.py [path/to/top-1m.csv]   -> clients/extension/src/data/well_known.json

Tranco (https://tranco-list.eu, Le Pochat et al., NDSS 2019) states no license of its own; its upstream sources
include CC BY-SA 4.0 and CC BY-NC 4.0 data, so the list is used non-commercially with attribution. Rank is a
popularity signal, not proof of safety: reviewer-confirmed high-risk hosts always override this list.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT = REPO / "data" / "private" / "public_datasets" / "tranco" / "top-1m.csv"
OUT = REPO / "clients" / "extension" / "src" / "data" / "well_known.json"
TOP = 10_000


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    if not src.is_file():
        if OUT.is_file():
            print(f"{src} not found; keeping the existing {OUT.name}")
            return 0
        raise SystemExit(f"{src} not found - download https://tranco-list.eu/top-1m.csv.zip and unzip it")
    domains = []
    with src.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].isdigit():
                domains.append(row[1].strip().lower())
                if len(domains) >= TOP:
                    break
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "Tranco top sites (https://tranco-list.eu), top 10,000; non-commercial use with "
                                         "attribution", "generated_from": src.name, "domains": domains},
                              separators=(",", ":")), encoding="utf-8")
    print(f"{len(domains)} domains -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
