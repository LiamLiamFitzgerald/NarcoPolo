"""Request cache for raw downloads: a request's SHA-256 names its file; raw/manifest.json records every file.

Manifest shape matches sim/raw.py: {"latest": {...}, "files": {path: {request, sha256, download_time, licence}}}.
"latest" is P1's contract (DECISIONS.md 2026-11-27 17:25); record() leaves it untouched.
"""

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from core.io import raw_root

# ingest.run fetches scenes on several threads: one manifest read-modify-write at a time
_LOCK = threading.RLock()


def request_key(request: dict) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()  # streams: scenes are ~150 MB


def _load_manifest(raw: Path) -> dict:
    manifest = raw / "manifest.json"
    if not manifest.exists():
        return {"files": {}}
    return json.loads(manifest.read_text(encoding="utf-8"))


def cached(request: dict) -> Path | None:
    raw = raw_root()
    key = request_key(request)
    with _LOCK:
        files = _load_manifest(raw)["files"]
    for rel, entry in files.items():
        path = raw / rel
        if request_key(entry["request"]) == key and path.is_file():
            return path
    return None


def record(request: dict, path: Path, licence: str) -> None:
    if not licence or not licence.strip():
        raise ValueError("every raw file needs a licence")
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = raw_root()
    rel = path.resolve().relative_to(raw.resolve()).as_posix()  # ValueError if outside raw/
    digest = _sha256(path)  # outside the lock: hashing a ~700 MB scene takes seconds
    with _LOCK:
        _write(raw, rel, request, digest, licence)


def _write(raw: Path, rel: str, request: dict, digest: str, licence: str) -> None:
    manifest = _load_manifest(raw)
    manifest["files"][rel] = {
        "request": request,
        "sha256": digest,
        "download_time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "licence": licence,
    }
    # write-then-rename so a crash mid-write never corrupts the manifest
    tmp = raw / "manifest.json.tmp"
    tmp.write_text(
        json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, raw / "manifest.json")
