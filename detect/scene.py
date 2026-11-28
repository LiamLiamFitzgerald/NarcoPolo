"""Load a radar scene as linear sigma0 and mask it."""

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import ndimage

from detect._common import CFG


def to_linear(db100: np.ndarray, nodata: float | None = None) -> np.ndarray:
    """int16 sigma0 in dB x 100 -> linear power; nodata pixels -> NaN. CFAR must never run on dB (spec warning)."""
    v = np.asarray(db100)
    out = 10 ** (v.astype(np.float64) / 1000)
    if nodata is not None:
        out[v == nodata] = np.nan  # else -32768 becomes ~1e-33 and drags the background down (#291)
    return out


def _scene_file(pass_id: str, raw_dir: Path) -> Path:
    """raw/s1/<pass_id>.tif if it exists (validate.injection_test passes file names), else the <hash>.tif whose
    .json says pass_id: P2 names scenes by request hash, not by the catalogue pass_id (#291)."""
    if (direct := raw_dir / "s1" / f"{pass_id}.tif").exists():
        return direct
    hits = [
        js.with_suffix(".tif")
        for js in sorted((raw_dir / "s1").glob("*.json"))
        if json.loads(js.read_text()).get("pass_id") == pass_id and js.with_suffix(".tif").exists()
    ]
    if len(hits) != 1:
        raise FileNotFoundError(
            f"{len(hits)} scenes in {raw_dir / 's1'} for pass {pass_id}, need exactly 1"
        )
    return hits[0]


def load_scene(
    pass_id: str, raw_dir: Path = Path("raw")
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """raw/s1/<hash>.tif (VV, VH) and its .json -> (vv, vh, meta) in linear sigma0, nodata as NaN.

    Fails loudly on a scene that isn't EPSG:32629 int16, or that has no valid pixel. meta gains x_left/y_top.
    """
    import rasterio  # only needed for real scenes

    tif = _scene_file(pass_id, raw_dir)
    with rasterio.open(tif) as src:
        if src.crs is None or src.crs.to_epsg() != 32629 or src.dtypes[:2] != ("int16", "int16"):
            raise ValueError(
                f"{tif}: expected EPSG:32629 int16 VV, VH; got {src.crs}, {src.dtypes}"
            )
        vv, vh = src.read(1), src.read(2)
        x_left, y_top, nodata = src.transform.c, src.transform.f, src.nodata
    meta = json.loads(tif.with_suffix(".json").read_text()) | {"x_left": x_left, "y_top": y_top}
    vv, vh = to_linear(vv, nodata), to_linear(vh, nodata)
    if not np.isfinite(vv).any():
        raise ValueError(f"{tif}: every pixel is nodata")
    return vv, vh, meta


def _earlier_median(
    meta: dict[str, Any], raw_dir: Path, n: int
) -> tuple[np.ndarray, np.ndarray] | None:
    """Per-pixel median (VV, VH) of the n latest scenes of the same relative orbit strictly before this pass
    (#341, fixed-target suppression). Only scenes on this scene's exact grid window count. None if fewer than n:
    never this pass itself or a later one."""
    t = pd.Timestamp(meta["start_time"])
    earlier = []
    for js in sorted((raw_dir / "s1").glob("*.json")):
        m = json.loads(js.read_text())
        if (
            m.get("relative_orbit") == meta.get("relative_orbit")
            and pd.Timestamp(m["start_time"]) < t
        ):
            earlier.append((pd.Timestamp(m["start_time"]), m["pass_id"]))
    stack: list[tuple[np.ndarray, np.ndarray]] = []
    for _, pid in sorted(earlier, reverse=True):
        vv, vh, m = load_scene(pid, raw_dir)
        if (m["x_left"], m["y_top"]) == (meta["x_left"], meta["y_top"]) and vv.shape == meta[
            "shape"
        ]:
            stack.append((vv.astype(np.float32), vh.astype(np.float32)))
        if len(stack) == n:
            return (
                np.nanmedian([a for a, _ in stack], axis=0),
                np.nanmedian([b for _, b in stack], axis=0),
            )
    return None


def apply_masks(img: np.ndarray, land: np.ndarray, static: np.ndarray) -> np.ndarray:
    """Land plus a land_buffer_m buffer, and static objects, set to NaN (never 0)."""
    land = np.asarray(land).astype(bool)
    near_land = ndimage.distance_transform_edt(~land) * CFG["pixel_m"] <= CFG["land_buffer_m"]
    out = np.array(img, dtype=np.float64)
    out[near_land | np.asarray(static).astype(bool)] = np.nan
    return out
