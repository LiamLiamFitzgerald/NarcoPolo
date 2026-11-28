"""The simulator's own Gi* and CUSUM for its stand-in fuse/cells (#167). Own code: nothing from detectors/ is
imported, so a bug in P6's detectors cannot hide in the simulator too. Formulas: docs/shared.md (Gi* of y over
binary distance-band weights, self included; A1 Poisson likelihood-ratio CUSUM)."""

import numpy as np
import pandas as pd

from core.grid import FINE


def cusum(
    cell: np.ndarray,
    kind: np.ndarray,
    day: np.ndarray,
    c: np.ndarray,
    mu: np.ndarray,
    rho: float,
    h: float,
) -> np.ndarray:
    """Per (cell, event type) over its observed days in order, phi = 1: S = max(0, S + C ln rho - (rho - 1) mu).
    Each row gets S before the reset to 0 that follows S > h."""
    inc = c * np.log(rho) - (rho - 1) * mu
    order = np.lexsort((day, kind, cell))
    out = np.zeros(len(c))
    s, prev = 0.0, None
    for i in order:
        if (cell[i], kind[i]) != prev:
            s, prev = 0.0, (cell[i], kind[i])
        s = max(0.0, s + inc[i])
        out[i] = s
        if s > h:
            s = 0.0
    return out


def gi_star(
    cell: np.ndarray,
    kind: np.ndarray,
    week: np.ndarray,
    c: np.ndarray,
    mu: np.ndarray,
    band_m: float,
) -> np.ndarray:
    """Weekly Gi* z of y = (sum C + 0.5) / (sum mu + 0.5) over each week's observed cells of one event type; every
    row gets its cell-week's z."""
    f = pd.DataFrame({"cell": cell, "kind": kind, "week": week, "c": c, "mu": mu})
    w = f.groupby(["kind", "week", "cell"], as_index=False)[["c", "mu"]].sum()
    ij = w["cell"].str.split("_", expand=True)
    w["x"], w["y"] = ij[1].astype(float) * FINE, ij[2].astype(float) * FINE
    w["z"] = 0.0
    for idx in w.groupby(["kind", "week"]).indices.values():
        g = w.iloc[idx]
        y = ((g["c"] + 0.5) / (g["mu"] + 0.5)).to_numpy()
        x, yy = g["x"].to_numpy(), g["y"].to_numpy()
        near = (
            np.hypot(x[:, None] - x[None, :], yy[:, None] - yy[None, :]) <= band_m
        )  # self included
        n, W = len(y), near.sum(1)
        s = (
            y.std() if np.ptp(y) > 1e-9 * max(abs(y.mean()), 1.0) else 0.0
        )  # flat week: no signal, not noise
        den = s * np.sqrt((n * W - W**2) / max(n - 1, 1))
        z = np.divide(near @ y - y.mean() * W, den, out=np.zeros(n), where=den > 0)
        w.loc[w.index[idx], "z"] = z
    key = pd.MultiIndex.from_frame(w[["kind", "week", "cell"]])
    return (
        w.set_index(key)["z"]
        .reindex(pd.MultiIndex.from_frame(f[["kind", "week", "cell"]]))
        .to_numpy()
    )
