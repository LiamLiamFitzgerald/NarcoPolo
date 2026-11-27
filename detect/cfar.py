"""Cell-averaging CFAR on linear power."""

import numpy as np
import pandas as pd
from scipy import ndimage, optimize, stats

from detect._standin import CFG


def estimate_enl(img: np.ndarray, patch: tuple[slice, slice]) -> float:
    """Equivalent number of looks, mean^2 / variance, on a patch of open calm sea."""
    v = img[patch]
    v = v[np.isfinite(v)]
    return float(v.mean() ** 2 / v.var())


def _box_sum(a: np.ndarray, size: int) -> np.ndarray:
    return ndimage.uniform_filter(a, size=size, mode="constant", cval=0.0) * size**2


def background(img: np.ndarray, outer: int = CFG["cfar_outer"], guard: int = CFG["cfar_guard"]) -> np.ndarray:
    """Mean of the ring between the outer window and the guard window, skipping NaN pixels.

    Linear power only. Masked (NaN) pixels count neither in the sum nor in the pixel count,
    so the coast does not drag the background down. Pixels with an empty ring get NaN.
    """
    valid = np.isfinite(img)
    vals = np.where(valid, img, 0.0)
    s = _box_sum(vals, outer) - _box_sum(vals, guard)
    n = _box_sum(valid.astype(np.float64), outer) - _box_sum(valid.astype(np.float64), guard)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0.5, s / n, np.nan)


def alpha(L: float, p_fa: float = CFG["p_fa"]) -> float:
    """Threshold multiplier from the gamma speckle tail: P(I / mean > alpha) = p_fa."""
    return float(stats.gamma.isf(p_fa, a=L, scale=1 / L))


def flag(img: np.ndarray, mu_b: np.ndarray, alpha: float) -> np.ndarray:
    """Pixels brighter than alpha times their background. NaN pixels are never flagged."""
    with np.errstate(invalid="ignore"):
        return img > alpha * mu_b


CLUSTER_COLUMNS = ["row", "col", "x_m", "y_m", "n_px", "peak_ratio_db", "peak_db"]


def clusters(mask: np.ndarray, img: np.ndarray, mu_b: np.ndarray, *, meta: dict) -> pd.DataFrame:
    """8-connected blobs of cluster_px pixels: centroid, pixel count, peak I / mu_b in dB.

    meta gives the scene's top-left corner (x_left, y_top) in metres. peak_db is the blob's
    peak sigma0 in dB, which the ghost rule compares against.
    """
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if n == 0:
        return pd.DataFrame(columns=CLUSTER_COLUMNS)
    idx = np.arange(1, n + 1)
    n_px = ndimage.sum_labels(mask, lab, idx).astype(int)
    rc = np.array(ndimage.center_of_mass(mask, lab, idx)).reshape(-1, 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        peak_ratio = ndimage.maximum(np.nan_to_num(img / mu_b), lab, idx)
    peak = ndimage.maximum(np.nan_to_num(img), lab, idx)
    px = CFG["pixel_m"]
    df = pd.DataFrame({
        "row": rc[:, 0], "col": rc[:, 1],
        "x_m": meta["x_left"] + (rc[:, 1] + 0.5) * px, "y_m": meta["y_top"] - (rc[:, 0] + 0.5) * px,
        "n_px": n_px, "peak_ratio_db": 10 * np.log10(peak_ratio), "peak_db": 10 * np.log10(peak),
    })  # fmt: skip
    lo, hi = CFG["cluster_px"]
    return df[df["n_px"].between(lo, hi)].reset_index(drop=True)


def merge_pols(vv: pd.DataFrame, vh: pd.DataFrame, gate_m: float = CFG["pol_agree_m"]) -> pd.DataFrame:
    """Pair VV and VH clusters one-to-one within gate_m into single candidates.

    Paired: pol_agree, VV position, n_px = the larger count. Unpaired clusters stay, with
    the other polarisation's peak ratio NaN (run_pass fills it from the image).
    """
    pairs: list[tuple[int, int]] = []
    if len(vv) and len(vh):
        d = np.hypot(
            vv["x_m"].to_numpy()[:, None] - vh["x_m"].to_numpy(), vv["y_m"].to_numpy()[:, None] - vh["y_m"].to_numpy()
        )
        r, c = optimize.linear_sum_assignment(np.where(d <= gate_m, d, 1e9))
        pairs = [(i, j) for i, j in zip(r, c, strict=True) if d[i, j] <= gate_m]
    pi, pj = [i for i, _ in pairs], [j for _, j in pairs]
    a, b = vv.iloc[pi].reset_index(drop=True), vh.iloc[pj].reset_index(drop=True)
    both = a[["row", "col", "x_m", "y_m"]].assign(
        pol_agree=True, n_px=np.maximum(a["n_px"], b["n_px"]), peak_ratio_vv_db=a["peak_ratio_db"],
        peak_ratio_vh_db=b["peak_ratio_db"], peak_db=np.maximum(a["peak_db"], b["peak_db"]),
    )  # fmt: skip
    keep = ["row", "col", "x_m", "y_m", "n_px", "peak_db"]
    only_vv = vv.drop(index=vv.index[pi])
    only_vh = vh.drop(index=vh.index[pj])
    only_vv = only_vv[keep].assign(pol_agree=False, peak_ratio_vv_db=only_vv["peak_ratio_db"], peak_ratio_vh_db=np.nan)
    only_vh = only_vh[keep].assign(pol_agree=False, peak_ratio_vv_db=np.nan, peak_ratio_vh_db=only_vh["peak_ratio_db"])
    parts = [p for p in (both, only_vv, only_vh) if len(p)]
    if not parts:
        return pd.DataFrame(columns=[*keep, "pol_agree", "peak_ratio_vv_db", "peak_ratio_vh_db"])
    return pd.concat(parts, ignore_index=True)


def size_class(n_px):
    """1-4 px small, 5-20 medium, more large (very rough at 20 m resolution). Scalar or array."""
    n = np.asarray(n_px)
    out = np.where(n <= CFG["size_small_max_px"], "small", np.where(n <= CFG["size_medium_max_px"], "medium", "large"))
    return out.item() if out.ndim == 0 else out
