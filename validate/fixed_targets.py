"""Fixed-target suppression for the small-boat CFAR (#334): a measurement on the simulator, and the spec for P4.

Baseline: P4's CFAR on the pass image at its current p_fa. Candidate: the pass image divided by the per-pixel
median of the n passes *before* it (never the pass itself or a later one), then the same CFAR at
validate.fixed_target_p_fa. Rocks, buoys and fish farms divide out; a boat, new on this pass, does not.
P4's CFAR is imported and called, never changed.

Per scored pass: recall of planted boats (recovered if a candidate is within validate.injection_match_m),
false alarms on fixed targets (candidates within validate.persistence_radius_m of one) and false alarms on open
sea (every other candidate), per km2.
"""

from typing import Any

import numpy as np
import pandas as pd

from detect import cfar
from sim.stack import Stack

PX_M = 10.0  # docs/shared.md, Data dictionary: 10 m pixels
COLUMNS = ["pass", "method", "n_boats", "recall", "fa_fixed", "fa_sea_per_km2"]


def median_ratio(images: np.ndarray, k: int, n: int) -> np.ndarray:
    """Pass k over the per-pixel median of passes k-n .. k-1. Raises if fewer than n earlier passes exist."""
    if k < n:
        raise ValueError(f"pass {k} has only {k} earlier passes; the median needs {n}")
    return images[k] / np.median(images[k - n : k], axis=0)


def _candidates(img: np.ndarray, p_fa: float, enl: float) -> np.ndarray:
    mu_b = cfar.background(img)
    found = cfar.clusters(
        cfar.flag(img, mu_b, cfar.alpha(enl, p_fa)), img, mu_b, meta={"x_left": 0.0, "y_top": 0.0}
    )
    return found[["row", "col"]].to_numpy(float)


def _near(a: np.ndarray, b: np.ndarray, px: float) -> np.ndarray:
    """For each row of a: is any row of b within px pixels?"""
    if not len(a) or not len(b):
        return np.zeros(len(a), bool)
    return (np.hypot(a[:, None, 0] - b[None, :, 0], a[:, None, 1] - b[None, :, 1]) <= px).any(
        axis=1
    )


def score_pass(
    img: np.ndarray, boats: np.ndarray, fixed: np.ndarray, p_fa: float, cfg: Any
) -> dict:
    v = cfg["validate"]
    cand = _candidates(img, p_fa, cfg["p4"]["enl"])
    match_px, persist_px = v["injection_match_m"] / PX_M, v["persistence_radius_m"] / PX_M
    on_fixed = _near(cand, fixed.astype(float), persist_px)
    on_boat = _near(cand, boats.astype(float), match_px)
    sea_km2 = img.size * (PX_M / 1000) ** 2
    return {
        "n_boats": len(boats),
        "recall": float(_near(boats.astype(float), cand, match_px).mean())
        if len(boats)
        else np.nan,
        "fa_fixed": int((on_fixed & ~on_boat).sum()),
        "fa_sea_per_km2": float((~on_fixed & ~on_boat).sum() / sea_km2),
    }


def compare(stack: Stack, cfg: Any) -> pd.DataFrame:
    """One row per scored pass and method. Passes before the median has its n passes are not scored."""
    n, rows = int(cfg["validate"]["fixed_target_history"]), []
    for k in range(n, len(stack.images)):
        b = stack.boats.loc[stack.boats["pass"] == k, ["row", "col"]].to_numpy()
        base = score_pass(stack.images[k], b, stack.fixed, cfg["p4"]["p_fa"], cfg)
        ratio = median_ratio(stack.images, k, n)
        cand = score_pass(ratio, b, stack.fixed, cfg["validate"]["fixed_target_p_fa"], cfg)
        rows += [
            {"pass": k, "method": "baseline", **base},
            {"pass": k, "method": "median_ratio", **cand},
        ]
    return pd.DataFrame(rows, columns=COLUMNS)


def summary(per_pass: pd.DataFrame) -> pd.DataFrame:
    """Mean per method over the scored passes: recall, fixed-target false alarms per pass, sea false alarms per km2."""
    return per_pass.groupby("method")[["recall", "fa_fixed", "fa_sea_per_km2"]].mean()
