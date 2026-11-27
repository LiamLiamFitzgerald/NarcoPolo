"""Injection test (docs/specs/P1.md, Validation table): Gaussian spots in linear sigma0, rerun detect.run_pass.

Each pass's chip gets n_per_pass spots (sigma 1 px) at random sea pixels, peak = brightness_db over the local
clutter mean, added in linear power (never in dB). P4's run_pass then runs on the modified chip with the same
masks. A spot is recovered if a candidate lies within validate.injection_match_m (spec: 30 m); every other
candidate is a false alarm, counted per km2 of searched sea. On real data those include real, unlisted targets,
so the rate is an upper bound.
"""

import importlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import ndimage

from core import io
from core.config import load

COLUMNS = ["brightness_db", "recall", "false_alarms_per_km2"]
PX_M = 10.0  # docs/shared.md, Data dictionary: raw/s1 and the reference masks are 10 m pixels
SIGMA_PX = 1.0  # spec: Gaussian spot, sigma = 1 px


def _add_spot(img: np.ndarray, r: int, c: int, db: float, mean: float) -> None:
    """Add a sigma-1-px Gaussian in linear power so pixel (r, c) is `db` over `mean` (in place)."""
    h, w = img.shape
    k = int(np.ceil(4 * SIGMA_PX))  # the Gaussian is < 0.04% of its peak beyond 4 sigma
    rr, cc = np.mgrid[max(r - k, 0) : min(r + k + 1, h), max(c - k, 0) : min(c + k + 1, w)]
    amp = mean * (10 ** (db / 10) - 1)
    img[rr, cc] += amp * np.exp(-((rr - r) ** 2 + (cc - c) ** 2) / (2 * SIGMA_PX**2))


def _masks(cfg: Any, vv: np.ndarray, meta: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    """(land, static) on the chip's grid: P3's reference rasters if they exist, else land derived from the chip."""
    land_tif = io.raster_path("reference/land_mask_10m")
    if land_tif.exists():
        import rasterio

        out = []
        for name in ("reference/land_mask_10m", "reference/static_mask_10m"):
            with rasterio.open(io.raster_path(name)) as src:
                r0 = round((src.transform.f - meta["y_top"]) / PX_M)
                c0 = round((meta["x_left"] - src.transform.c) / PX_M)
                out.append(src.read(1)[r0 : r0 + vv.shape[0], c0 : c0 + vv.shape[1]].astype(bool))
        return out[0], out[1]
    # shortcut: no reference masks (the simulator writes none). Land = pixels whose local mean dB, over P3's
    # static window, is at least P3's static_db over the chip median; P4's land buffer then widens it.
    ref = cfg["reference"]
    db = 10 * np.log10(np.maximum(vv, np.finfo(float).tiny))
    local = ndimage.uniform_filter(db, size=int(ref["static_window_px"]), mode="nearest")
    land = local >= np.median(local) + float(ref["static_db"])
    return land, np.zeros_like(land)


def injection_test(
    pass_ids: list[str], brightness_db: list[float], n_per_pass: int, seed: int
) -> pd.DataFrame:
    try:
        run_pass = importlib.import_module("detect.pipeline").run_pass
        scene = importlib.import_module("detect.scene")
        background = importlib.import_module("detect.cfar").background
        load_scene, apply_masks = scene.load_scene, scene.apply_masks
    except (ImportError, AttributeError):  # P4's detector not on integration yet
        return pd.DataFrame(columns=COLUMNS)
    cfg, _ = load(io.CONFIG_PATH)
    match_px = float(cfg["validate"]["injection_match_m"]) / PX_M
    rng = np.random.default_rng(seed)
    rows = []
    scenes = {p: load_scene(p, Path(io.raw_root())) for p in pass_ids}
    for db in brightness_db:
        found = n = n_fa = 0
        sea_km2 = 0.0
        for p in pass_ids:
            vv, vh, meta = scenes[p]
            land, static = _masks(cfg, vv, meta)
            mu = {
                pol: background(apply_masks(x, land, static)) for pol, x in (("vv", vv), ("vh", vh))
            }
            sea = (
                np.isfinite(apply_masks(vv, land, static))
                & np.isfinite(mu["vv"])
                & np.isfinite(mu["vh"])
            )
            spots = _positions(rng, sea, n_per_pass, 2 * match_px)
            vv2, vh2 = vv.copy(), vh.copy()
            for r, c in spots:
                _add_spot(vv2, r, c, db, float(mu["vv"][r, c]))
                _add_spot(vh2, r, c, db, float(mu["vh"][r, c]))
            cands = run_pass(p, img=(vv2, vh2, meta), masks=(land, static))
            hit = np.zeros(len(cands), dtype=bool)
            if len(spots) and len(cands):
                d = np.hypot(
                    cands["row"].to_numpy()[:, None] - spots[:, 0][None, :],
                    cands["col"].to_numpy()[:, None] - spots[:, 1][None, :],
                )
                hit = (d <= match_px).any(axis=1)
                found += int((d <= match_px).any(axis=0).sum())
            n += len(spots)
            n_fa += int((~hit).sum())
            sea_km2 += sea.sum() * PX_M**2 / 1e6
        rows.append({
            "brightness_db": float(db),
            "recall": found / n if n else np.nan,  # no sea pixels: unobserved, not zero
            "false_alarms_per_km2": n_fa / sea_km2 if sea_km2 else np.nan,
        })  # fmt: skip
    return pd.DataFrame(rows, columns=COLUMNS)


def _positions(rng: np.random.Generator, sea: np.ndarray, n: int, min_px: float) -> np.ndarray:
    """Up to n random sea pixels (row, col), each more than min_px from the others so matches are unambiguous."""
    cand = np.argwhere(sea)
    picked: list[np.ndarray] = []
    for i in rng.permutation(len(cand)):
        if len(picked) == n:
            break
        if all(np.hypot(*(cand[i] - q)) > min_px for q in picked):
            picked.append(cand[i])
    return np.array(picked, dtype=int).reshape(-1, 2)
