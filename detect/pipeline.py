"""Per-pass detection and the full run to detect/detections.parquet."""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core import io
from core.schemas import SCHEMAS
from detect._common import CFG, cell_ids
from detect.cfar import (
    _censored_background,
    alpha,
    background,
    clusters,
    flag,
    merge_pols,
    size_class,
)
from detect.ghost import azimuth_heading, ghost_offset_m, is_ghost
from detect.pboat import features, predict_pboat
from detect.scene import apply_masks, load_scene


def _read_masks(meta: dict[str, Any], shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """reference/land_mask_10m and static_mask_10m (core.io.raster_path), cut to the scene's window on the region grid."""
    import rasterio

    out = []
    for name in ("reference/land_mask_10m", "reference/static_mask_10m"):
        with rasterio.open(io.raster_path(name)) as src:
            r0 = round((src.transform.f - meta["y_top"]) / CFG["pixel_m"])
            c0 = round((meta["x_left"] - src.transform.c) / CFG["pixel_m"])
            out.append(src.read(1)[r0 : r0 + shape[0], c0 : c0 + shape[1]])
    return out[0], out[1]


def _ratio_db_at(img: np.ndarray, mu_b: np.ndarray, rows: pd.Series, cols: pd.Series) -> np.ndarray:
    """Brightest valid I / mu_b in dB in the 3 x 3 pixels round each centre; 0 dB if all are masked."""
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.pad(img / mu_b, 1, constant_values=np.nan)
    out = []
    for r, c in zip(np.rint(rows).astype(int), np.rint(cols).astype(int), strict=True):
        win = ratio[r : r + 3, c : c + 3]  # padded by 1, so this is centred on (r, c)
        out.append(10 * np.log10(np.nanmax(win)) if np.isfinite(win).any() else 0.0)
    return np.array(out)


def run_pass(
    pass_id: str,
    img: tuple[np.ndarray, np.ndarray, dict[str, Any]] | None = None,
    *,
    masks: tuple[np.ndarray, np.ndarray] | None = None,
    root: Path | None = None,
) -> pd.DataFrame:
    """CFAR on VV and VH, merged candidates with size class, ghost flag and cell_id (no p_boat yet).

    img: (vv, vh, meta) in linear sigma0; validate.injection_test passes a modified chip here.
    masks: (land, static) on the scene's grid; read from the reference rasters when None.
    root: the raw/ directory (default core.io.raw_root()).
    """
    vv, vh, meta = img if img is not None else load_scene(pass_id, root or io.raw_root())
    land, static = masks if masks is not None else _read_masks(meta, vv.shape)
    a = alpha(CFG["enl"], CFG["p_fa"])
    per_pol = {}
    for pol, raw in (("vv", vv), ("vh", vh)):
        m = apply_masks(raw, land, static)
        mu = _censored_background(m, a) if CFG["cfar_censor"] else background(m)
        per_pol[pol] = (m, mu, clusters(flag(m, mu, a), m, mu, meta=meta))
    cands = merge_pols(per_pol["vv"][2], per_pol["vh"][2])
    # a blob seen in one polarisation only gets the other's measured ratio at its centre
    for pol in ("vv", "vh"):
        col, miss = f"peak_ratio_{pol}_db", cands[f"peak_ratio_{pol}_db"].isna()
        m, mu, _ = per_pol[pol]
        cands.loc[miss, col] = _ratio_db_at(m, mu, cands.loc[miss, "row"], cands.loc[miss, "col"])
    heading, offset = azimuth_heading(meta), ghost_offset_m(meta)
    cands["ghost"] = [is_ghost(c, vv, heading, offset) for _, c in cands.iterrows()]
    cands["size_class"] = size_class(cands["n_px"].to_numpy()) if len(cands) else []
    cands["n_px"] = cands["n_px"].astype(int)
    cands["pol_agree"] = cands["pol_agree"].astype(bool)
    cands["pass_id"] = pass_id
    cands["time_utc"] = pd.to_datetime(
        pd.Series(meta["start_time"], index=cands.index), utc=True
    )  # naive = UTC
    cands["cell_id"] = (
        cell_ids(cands["x_m"].to_numpy(), cands["y_m"].to_numpy()) if len(cands) else []
    )
    cands["det_id"] = [f"{pass_id}-{i}" for i in range(len(cands))]
    return cands


DETECTIONS_COLUMNS = list(SCHEMAS["detect/detections"].columns)


def run_all(model: Any, exposure: pd.DataFrame, *, raw: Path | None = None) -> pd.DataFrame:
    """Every pass in coverage/exposure -> the detect/detections frame (schema-checked; run() writes it).

    Candidates in cells where that pass is not calm (or not covered) are dropped: those cells have small-boat
    exposure 0, so a pass with no calm cell is not read at all. A calm pass without a scene is an error: its
    cells have exposure, and no detections there would read as zero boats. model is the fitted fit_pboat result.
    """
    calm = exposure.loc[exposure["calm"].astype(bool), ["cell_id", "pass_id"]].drop_duplicates()
    frames = [run_pass(p, root=raw) for p in calm["pass_id"].unique()]
    dets = pd.concat(frames, ignore_index=True)
    dets = dets.merge(calm, on=["cell_id", "pass_id"], how="inner")
    dets["p_boat"] = predict_pboat(model, features(dets, exposure)) if len(dets) else []
    return SCHEMAS["detect/detections"].validate(dets[DETECTIONS_COLUMNS])
