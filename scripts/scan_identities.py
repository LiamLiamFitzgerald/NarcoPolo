#!/usr/bin/env python3
"""Fail if committed outputs contain anything that looks like a vessel identifier.

Usage: scan_identities.py <folder> [<folder> ...]   (missing folders are skipped; tests/ folders are skipped)
"""

import re
import sys
from pathlib import Path

PATTERNS = {
    "MMSI (stand-alone 9-digit number)": re.compile(r"(?<![\d.])\d{9}(?![\d.])"),
    "IMO number": re.compile(r"\bIMO[\s:#-]*\d{7}\b", re.IGNORECASE),
    "call sign field": re.compile(r"call[\s_-]?sign", re.IGNORECASE),
    "MMSI field": re.compile(r"\bmmsi\b", re.IGNORECASE),
}
SUFFIXES = {".json", ".geojson", ".html", ".js", ".csv", ".md", ".txt"}

hits = []
for folder in sys.argv[1:]:
    root = Path(folder)
    if not root.exists():
        continue
    for f in root.rglob("*"):
        if not f.is_file() or f.suffix not in SUFFIXES or "tests" in f.parts:
            continue
        text = f.read_text(errors="ignore")
        for name, pat in PATTERNS.items():
            for m in pat.finditer(text):
                hits.append(f"{f}: {name}: {m.group(0)!r}")

if hits:
    print("Possible vessel identifiers found:")
    print("\n".join(hits[:50]))
    sys.exit(1)
print("Identity scan passed.")
