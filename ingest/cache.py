"""Request cache for raw downloads: a request's SHA-256 names its file; raw/manifest.json records every file."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

RAW_DIR = Path("raw")


def request_key(request: dict) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_manifest(raw_dir: Path) -> dict:
    # {"files": [...], "latest": {...}}; "latest" is P1's contract (DECISIONS.md 2026-11-27 17:25)
    manifest = raw_dir / "manifest.json"
    if not manifest.exists():
        return {"files": []}
    return json.loads(manifest.read_text(encoding="utf-8"))


def cached(request: dict, *, raw_dir: Path = RAW_DIR) -> Path | None:
    key = request_key(request)
    for entry in reversed(_load_manifest(raw_dir)["files"]):
        path = raw_dir / entry["path"]
        if entry["hash"] == key and path.exists():
            return path
    return None


def record(request: dict, path: Path, licence: str, *, raw_dir: Path = RAW_DIR) -> None:
    if not licence or not licence.strip():
        raise ValueError("every raw file needs a licence")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    rel = path.resolve().relative_to(raw_dir.resolve())  # ValueError if outside raw/
    manifest = _load_manifest(raw_dir)
    manifest["files"].append(
        {
            "path": rel.as_posix(),
            "request": request,
            "hash": request_key(request),
            "time_utc": datetime.now(UTC).isoformat(),
            "licence": licence,
        }
    )
    # write-then-rename so a crash mid-write never corrupts the manifest
    tmp = raw_dir / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, raw_dir / "manifest.json")
