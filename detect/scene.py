"""Load a radar scene as linear sigma0 and mask it."""

import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage

from detect._standin import CFG


def to_linear(db100: np.ndarray) -> np.ndarray:
    """int16 sigma0 in dB x 100 -> linear power. CFAR must never run on dB (spec warning)."""
    return 10 ** (np.asarray(db100, dtype=np.float64) / 1000)


def load_scene(pass_id: str, raw_dir: Path = Path("raw")) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """raw/s1/<pass_id>.tif (VV, VH) and its .json -> (vv, vh, meta) in linear sigma0.

    TODO(P2): assumes the file hash is the pass_id; meta gains x_left/y_top from the GeoTIFF.
    """
    import rasterio  # only needed for real scenes

    tif = raw_dir / "s1" / f"{pass_id}.tif"
    with rasterio.open(tif) as src:
        vv, vh = src.read(1), src.read(2)
        x_left, y_top = src.transform.c, src.transform.f
    meta = json.loads(tif.with_suffix(".json").read_text()) | {"pass_id": pass_id, "x_left": x_left, "y_top": y_top}
    return to_linear(vv), to_linear(vh), meta


def apply_masks(img: np.ndarray, land: np.ndarray, static: np.ndarray) -> np.ndarray:
    """Land plus a land_buffer_m buffer, and static objects, set to NaN (never 0)."""
    land = np.asarray(land).astype(bool)
    near_land = ndimage.distance_transform_edt(~land) * CFG["pixel_m"] <= CFG["land_buffer_m"]
    out = np.array(img, dtype=np.float64)
    out[near_land | np.asarray(static).astype(bool)] = np.nan
    return out
