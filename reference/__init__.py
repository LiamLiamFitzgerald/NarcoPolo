"""Static map of normal at sea: cells and layers, masks, piers and travel times (docs/specs/P3.md)."""

import json

from core import io

_STAGES = (
    "reference/cells",
    "reference/land",
    "reference/piers",
    "reference/travel_hours",
    "reference/presence_2km",
)


def _raw_is_real() -> bool:
    """True when raw/manifest.json lists files and none is a simulator copy ("simulated") or an ingest stub ("stub").
    Without a manifest there is nothing real to build from."""
    path = io.raw_root() / "manifest.json"
    if not path.exists():
        return False
    files = json.loads(path.read_text()).get("files", {})
    fake = any(
        f.get("request", {}).get("simulated") or f.get("request", {}).get("stub")
        for f in files.values()
    )
    return bool(files) and not fake


def run() -> None:
    """make all. Simulator (or ingest stubs): `make sim` already wrote the reference files; check them and stop.
    Real raw/: build cells, land, piers, travel times, the 2 km presence (#208) and the rasters from raw/ and write
    them through core.io."""
    if not _raw_is_real():
        for name in _STAGES:
            io.read_stage(name)
        return
    from reference import _real

    r = _real.build()
    io.write_stage("reference/cells", r.cells, "real")
    io.write_stage("reference/land", r.land, "real")
    io.write_stage("reference/piers", r.piers, "real")
    io.write_stage("reference/travel_hours", r.travel, "real")
    io.write_stage("reference/presence_2km", r.presence, "real")
    for name, (array, pixel_m) in r.rasters.items():
        _real.write_raster(name, array, pixel_m)
