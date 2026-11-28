"""Weekly agent scores per 2 km cell (docs/learning.md R3): one definition shared by the trainer (validate/train.py)
and the site model in fuse, so the model scores the features it was fitted on."""

import numpy as np
import pandas as pd
from scipy.stats import poisson

from core.observed import Observed

AGENTS = ("oe", "midp", "gi", "cusum")  # R3: `link` is site-level only and enters through p_comb
_RHO = 2.0  # Poisson CUSUM shift, A1


def _midp(c: np.ndarray, mu: np.ndarray) -> np.ndarray:
    """-log10 of the upper mid-p, interpolated between floor(C) and ceil(C) for soft counts (A6)."""

    def pm(k: np.ndarray) -> np.ndarray:
        return poisson.sf(k, mu) + 0.5 * poisson.pmf(k, mu)

    lo = np.floor(c)
    f = c - lo
    p = (1 - f) * pm(lo) + f * pm(lo + 1)
    return -np.log10(np.clip(p, np.finfo(float).tiny, 1))


def _gi(ix: np.ndarray, iy: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Getis-Ord Gi* z of y over one week's observed cells; binary weights on the 8 surrounding 2 km cells, self
    included."""
    pos = {(int(i), int(j)): k for k, (i, j) in enumerate(zip(ix, iy, strict=True))}
    local, W = y.copy(), np.ones(len(y))
    for k, (i, j) in enumerate(zip(ix, iy, strict=True)):
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                nb = pos.get((int(i) + di, int(j) + dj)) if (di or dj) else None
                if nb is not None:
                    local[k] += y[nb]
                    W[k] += 1
    n, s = len(y), y.std()
    den = s * np.sqrt((n * W - W**2) / max(n - 1, 1))
    return np.divide(local - y.mean() * W, den, out=np.zeros(n), where=den > 0)


def weekly_scores(obs: pd.DataFrame, exp: pd.DataFrame) -> pd.DataFrame:
    """Weekly agent scores per fine cell from its observed rows only (exposure > 0; principle 4): a cell-week
    with no exposure has no row, never a zero. `date` is the week's Sunday, so Split.train keeps whole weeks."""
    seen = Observed(obs).observed_rows()
    seen = seen[seen["level"] == 2000]
    exp = exp[
        exp["fold"] == 0
    ]  # the live forecast only, as detectors uses it (#172, #198): NA is not live
    key = ["cell_id", "date", "event_type"]
    m = seen.merge(exp[[*key, "mu"]], on=key)
    d = pd.to_datetime(m["date"])
    m["date"] = (d + pd.to_timedelta(6 - d.dt.day_of_week, unit="D")).dt.normalize()
    w = m.groupby(["cell_id", "date"], as_index=False)[["count", "mu"]].sum()
    w = w.sort_values(["cell_id", "date"], ignore_index=True)
    c, mu = w["count"].to_numpy(float), w["mu"].to_numpy(float)
    y = (c + 0.5) / (mu + 0.5)
    w["oe"] = np.log(y)
    w["midp"] = _midp(c, mu)
    inc = c * np.log(_RHO) - (_RHO - 1) * mu
    cus = np.zeros(len(w))
    for idx in w.groupby("cell_id").indices.values():
        s = 0.0
        for i in idx:  # rows are in date order within a cell; unobserved weeks have no row
            s = max(0.0, s + inc[i])
            cus[i] = s
    w["cusum"] = cus
    parts = w["cell_id"].str.split("_", expand=True)
    ix, iy = parts[1].astype(int).to_numpy(), parts[2].astype(int).to_numpy()
    gi = np.zeros(len(w))
    for idx in w.groupby("date").indices.values():
        gi[idx] = _gi(ix[idx], iy[idx], y[idx])
    w["gi"] = gi
    return w


def site_features(
    sites: pd.DataFrame, observed: pd.DataFrame, expected: pd.DataFrame, T
) -> pd.DataFrame:
    """AGENTS columns per site (site_id = cell_id, A2): the site's latest observed week up to T's week. A site
    whose cell has no observed week up to T gets NaN, never zero (principle 4)."""
    w = weekly_scores(observed, expected)
    if T is not None:
        t = pd.Timestamp(T)
        w = w[w["date"] <= (t + pd.Timedelta(days=6 - t.day_of_week)).normalize()]
    last = w.sort_values("date").groupby("cell_id").tail(1).set_index("cell_id")
    return last.reindex(sites["site_id"])[list(AGENTS)].set_axis(sites.index)
