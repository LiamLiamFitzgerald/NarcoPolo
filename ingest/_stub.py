"""Shared by the offline stubs: cache-or-write, the region config and a minimal GeoTIFF writer.

shortcut: every fetch_* writes an empty or all-NaN placeholder in the raw/ shape and touches no network;
replace each body with the real download once its API names are checked (spec Warnings).
"""

import struct
from collections.abc import Callable
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio

from core.config import Config, load
from core.io import CONFIG_PATH, raw_root
from ingest.cache import cached, record

LICENCE = "stub placeholder, no third-party data"
Bbox = tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max (WGS84)


def config() -> Config:
    return load(CONFIG_PATH)[0]


def region(cfg: Config | None = None) -> Bbox:
    b = (cfg or config())["region_bbox"]
    return b["lon_min"], b["lat_min"], b["lon_max"], b["lat_max"]


def empty_gpkg(path: Path, layer: str, geometry_type: str) -> None:
    frame = gpd.GeoDataFrame({"id": pd.Series(dtype="int64")}, geometry=gpd.GeoSeries([], crs=4326))
    pyogrio.write_dataframe(frame, path, layer=layer, geometry_type=geometry_type)


def request(
    source: str, bbox: Bbox | None = None, start: date | None = None, end: date | None = None
) -> dict:
    """The cache key; "stub": True keeps a real download's request from ever hitting a stub file."""
    req: dict = {"source": source, "stub": True}
    if bbox is not None:
        req["bbox"] = [float(v) for v in bbox]
    if start is not None and end is not None:
        req["start"], req["end"] = start.isoformat(), end.isoformat()
    return req


def get(req: dict, rel: str, write: Callable[[Path], None]) -> Path:
    """Return the cached file for req, or write raw/<rel> and record it with a licence."""
    if (hit := cached(req)) is not None:
        return hit
    path = raw_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    write(path)
    record(req, path, LICENCE)
    return path


def geotiff(path: Path, bands: np.ndarray, x_left: float, y_top: float, px: float) -> None:
    """Uncompressed little-endian GeoTIFF, EPSG:32629, one plane per band; int16 or float32 (no raster lib installed)."""
    nb, h, w = bands.shape
    fmt = {3: "H", 4: "I", 12: "d"}
    planes = [b.astype(bands.dtype.newbyteorder("<")).tobytes() for b in bands]
    # projected, pixel-is-area, UTM 29N
    geokeys = [1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 32629]  # fmt: skip
    tags = [
        (256, 4, [w]), (257, 4, [h]), (258, 3, [bands.dtype.itemsize * 8] * nb), (259, 3, [1]),
        (262, 3, [1]), (273, 4, [0] * nb), (277, 3, [nb]), (278, 4, [h]),
        (279, 4, [len(p) for p in planes]), (284, 3, [2]),
        (339, 3, [3 if bands.dtype.kind == "f" else 2] * nb),
        (33550, 12, [px, px, 0.0]), (33922, 12, [0.0, 0.0, 0.0, x_left, y_top, 0.0]),
        (34735, 3, geokeys),
    ]  # fmt: skip
    pos = 8 + 2 + 12 * len(tags) + 4
    blob = lambda t, v: struct.pack(f"<{len(v)}{fmt[t]}", *v)
    extra_len = sum(len(blob(t, v)) for _, t, v in tags if len(blob(t, v)) > 4)
    offsets, at = [], pos + extra_len
    for p in planes:
        offsets.append(at)
        at += len(p)
    tags = [(tag, t, offsets if tag == 273 else v) for tag, t, v in tags]
    ifd, extra = bytearray(struct.pack("<H", len(tags))), bytearray()
    for tag, t, v in tags:
        b = blob(t, v)
        if len(b) > 4:
            ifd += struct.pack("<HHII", tag, t, len(v), pos + len(extra))
            extra += b
        else:
            ifd += struct.pack("<HHI", tag, t, len(v)) + b.ljust(4, b"\0")
    path.write_bytes(
        b"II*\x00" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + extra + b"".join(planes)
    )
