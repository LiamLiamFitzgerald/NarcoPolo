"""Sentinel-1 IW GRD passes and scenes: raw/s1/<hash>.tif (VV, VH int16 dB x 100) + raw/s1/<hash>.json."""

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ingest import _stub
from ingest.cache import record, request_key

_NODATA = -32768  # int16 minimum: a stub pixel holds no backscatter
_PX = 10.0  # m, the fixed region grid (issue 5)


def list_passes(bbox: _stub.Bbox, start: date, end: date) -> pd.DataFrame:
    """Every pass over bbox in [start, end]: pass_id, time, orbit_dir, rel_orbit, footprint. Stub: none."""
    return pd.DataFrame(
        {
            "pass_id": pd.Series(dtype="string"),
            "time": pd.Series(dtype="datetime64[ns, UTC]"),
            "orbit_dir": pd.Series(dtype="string"),
            "rel_orbit": pd.Series(dtype="int64"),
            "footprint": pd.Series(dtype="string"),
        }
    )


def select_passes(passes: pd.DataFrame, era5: Path) -> pd.DataFrame:
    """passes + downloaded flag. Stub: nothing selected until P3's calm thresholds are read."""
    return passes.assign(downloaded=False)


def fetch_scene(pass_: Mapping[str, Any]) -> Path:
    """One row of list_passes (`pass` is a Python keyword) -> raw/s1/<hash>.tif and .json; returns the .tif."""
    start = pd.Timestamp(pass_["time"]).isoformat()
    req = {**_stub.request("s1"), "pass_id": str(pass_["pass_id"]), "time": start}
    key = request_key(req)
    cfg = _stub.config()
    meta = {
        "scene_id": key,
        "pass_id": str(pass_["pass_id"]),
        "start_time": start,
        "orbit_direction": pass_["orbit_dir"],
        "relative_orbit": int(pass_["rel_orbit"]),
        "footprint": pass_["footprint"],
        "footprint_crs": "EPSG:4326",
        # openEO gives no annotation metadata (issue 6): null until it is read
        "incidence_min": None,
        "incidence_max": None,
        "prf_hz": None,
        "slant_range_m": None,
        "satellite_speed_ms": None,
        "heading_deg": None,
    }
    bands = np.full((2, 1, 1), _NODATA, dtype=np.int16)

    def write(path: Path) -> None:
        _stub.geotiff(path, bands, float(cfg["x0"]), float(cfg["y0"]) + _PX, _PX)
        meta_path = path.with_suffix(".json")
        meta_path.write_text(json.dumps(meta, indent=1))
        record({**req, "part": "metadata"}, meta_path, _stub.LICENCE)

    return _stub.get(req, f"s1/{key}.tif", write)
