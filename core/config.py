"""config.yaml -> a read-only mapping plus the SHA-256 of the file."""

import hashlib
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

Config = Mapping[str, Any]

# The four feeds whose latest date caps T (A11). P2 writes these into raw/manifest.json["latest"].
_FEEDS = ("radar", "gfw_presence", "gfw_sar", "era5")


def _freeze(x: Any) -> Any:
    if isinstance(x, dict):
        return MappingProxyType({k: _freeze(v) for k, v in x.items()})
    if isinstance(x, list):
        return tuple(_freeze(v) for v in x)
    return x


def load(path: str | Path = "config.yaml") -> tuple[Config, str]:
    raw = Path(path).read_bytes()
    return _freeze(yaml.safe_load(raw)), hashlib.sha256(raw).hexdigest()


def latest_dates(manifest: Mapping[str, Any]) -> dict[str, date]:
    """The latest date of each feed, from raw/manifest.json["latest"]; KeyError if a feed is missing."""
    latest = manifest["latest"]
    return {f: date.fromisoformat(latest[f]) for f in _FEEDS}


def snapshot_date(manifest: Mapping[str, Any]) -> date:
    """T = the earliest of the four feeds' latest dates; later days would count as 'looked, saw nothing'."""
    return min(latest_dates(manifest).values())
