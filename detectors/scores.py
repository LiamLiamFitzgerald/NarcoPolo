"""The four detectors and their fusion (docs/specs/P6.md). Tail surprise, BH, Gi* and CUSUM are issue 54;
the context rules and fusion are still stubs (issue 55)."""

from datetime import timedelta

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from core import io
from core.grid import neighbours
from core.observed import Observed
from detectors._common import PARAMS, _provenance

_KEY = ["cell_id", "date", "event_type"]


def pearson_z(C, mu, phi) -> np.ndarray:
    C, mu, phi = (np.asarray(a, float) for a in (C, mu, phi))
    return (C - mu) / np.sqrt(np.maximum(phi, 1) * mu)


def _pmid_int(c: np.ndarray, mu: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """P(X > c) + P(X = c) / 2 for integer c; X has mean mu, variance phi * mu (Poisson where phi <= 1)."""
    pois = (phi <= 1) | (mu <= 0)  # mu = 0: X is 0 for sure, whatever phi says
    out = np.empty_like(mu)
    m, k = mu[pois], c[pois]
    out[pois] = stats.poisson.sf(k, m) + 0.5 * stats.poisson.pmf(k, m)
    nb = ~pois
    n, p, k = mu[nb] / (phi[nb] - 1), 1 / phi[nb], c[nb]
    out[nb] = stats.nbinom.sf(k, n, p) + 0.5 * stats.nbinom.pmf(k, n, p)
    return out


def tail_pmid(C, mu, phi) -> np.ndarray:
    """Mid-p tail value; a soft count is interpolated between floor(C) and ceil(C), never rounded (A6)."""
    C, mu, phi = (np.asarray(a, float) for a in (C, mu, phi))
    lo, frac = np.floor(C), C - np.floor(C)
    return (1 - frac) * _pmid_int(lo, mu, phi) + frac * _pmid_int(lo + 1, mu, phi)


def bh(p, q=PARAMS["fdr_q"]) -> np.ndarray:
    """Benjamini-Hochberg flags. Call it once over the whole evaluation window, never per day or per cell."""
    p = np.asarray(p, float)
    return multipletests(p, alpha=q, method="fdr_bh")[0] if len(p) else np.zeros(0, bool)


def gi_star(C_week, mu_week, cells, band_m=PARAMS["gi_band_m"], perm=PARAMS["gi_perm"], seed=None):
    """Getis-Ord Gi* z of y = (C + 0.5) / (mu + 0.5) for one week's observed cells; binary DistanceBand weights,
    self included. This is esda.G_Local(star=True).Zs, the analytic z: `perm` and `seed` only drive esda's
    permutation p-value, which we don't keep, so the z is deterministic."""
    y = (np.asarray(C_week, float) + 0.5) / (np.asarray(mu_week, float) + 0.5)
    cells = list(cells)
    n = len(cells)
    idx = {c: i for i, c in enumerate(cells)}
    nbrs = neighbours(cells, band_m)
    W = np.array([1 + len(nbrs[c]) for c in cells], float)  # w_ii = 1 (star)
    local = y + np.array([y[[idx[j] for j in nbrs[c]]].sum() for c in cells])
    s = y.std()
    den = s * np.sqrt((n * W - W**2) / max(n - 1, 1))  # binary weights: sum w^2 = W
    num = local - y.mean() * W
    return np.divide(num, den, out=np.zeros(n), where=den > 0)


def cusum(C, mu, phi, rho=PARAMS["cusum_rho"], h=PARAMS["cusum_h"]) -> np.ndarray:
    """Poisson likelihood-ratio CUSUM over one cell's days in date order (A1). NaN C = unobserved day: S stays
    as it was. Returns S each day before any reset; S restarts at 0 after it exceeds h."""
    C, mu, phi = (np.asarray(a, float) for a in (C, mu, phi))
    inc = (C * np.log(rho) - (rho - 1) * mu) / np.maximum(phi, 1)
    out, S = np.empty(len(C)), 0.0
    for d, x in enumerate(inc):
        if not np.isnan(x):
            S = max(0.0, S + x)
        out[d] = S
        if S > h:
            S = 0.0
    return out


def context_small(layers, post_storm) -> np.ndarray:  # stub, issue 55
    return np.full(len(layers), 0.5)


def context_slowdown(layers, hours) -> np.ndarray:  # stub, issue 55
    return np.full(len(layers), 0.5)


def fuse(scores: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:  # stub, issue 55
    return np.full(len(scores), 0.5), np.zeros(len(scores), int)


def _weekly_gi(m: pd.DataFrame) -> np.ndarray:
    """Each row gets the gi_z of its cell's ISO week, per event type (observed rows only)."""
    week = pd.to_datetime(m["date"]).dt.to_period("W-SUN")
    sums = (
        m.assign(week=week)
        .groupby(["event_type", "week", "cell_id"], as_index=False)[["count", "mu"]]
        .sum()
    )
    sums["gi_z"] = 0.0
    for _, g in sums.groupby(["event_type", "week"]):
        sums.loc[g.index, "gi_z"] = gi_star(g["count"], g["mu"], g["cell_id"])
    return (
        m.assign(week=week)
        .merge(sums, on=["event_type", "week", "cell_id"], how="left")["gi_z"]
        .to_numpy()
    )


def run_cells() -> None:
    """aggregate/observed + forecast/expected -> fuse/cells.parquet, observed rows (E > 0) in the evaluation
    window only. CUSUM runs over all observed history so a build-up before the window still counts."""
    obs = Observed(io.read_stage("aggregate/observed")).observed_rows()
    m = obs.merge(io.read_stage("forecast/expected"), on=_KEY).sort_values(["date", "cell_id"])
    m["cusum_s"] = 0.0
    for _, g in m.groupby(["event_type", "cell_id"]):
        m.loc[g.index, "cusum_s"] = cusum(g["count"], g["mu"], g["phi"])
    T = io.read_snapshot()["T"]
    start = T - timedelta(days=T.weekday() + 21)  # Monday of the ISO week three weeks before T's
    m = m[pd.to_datetime(m["date"]).between(pd.Timestamp(start), pd.Timestamp(T))].reset_index(
        drop=True
    )
    p_mid = tail_pmid(m["count"], m["mu"], m["phi"])
    scores = m[_KEY].assign(
        p_mid=p_mid,
        bh_flag=bh(p_mid),
        gi_z=_weekly_gi(m),
        cusum_s=m["cusum_s"],
        context=context_small(
            m, None
        ),  # TODO(P6): issue 55, per event type, with layers and post_storm
    )
    scores["U"], scores["agreement"] = fuse(scores)
    io.write_stage("fuse/cells", scores, _provenance("aggregate/observed"))  # type: ignore[arg-type]
