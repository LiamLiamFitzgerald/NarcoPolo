"""The four detectors and their fusion (docs/specs/P6.md): tail surprise + BH, Gi*, CUSUM (issue 54), context and
rank fusion (issue 55)."""

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


def _fact(known, yes) -> np.ndarray:
    """1.0 / 0.0 for a yes/no fact, NaN where its input is unknown."""
    return np.where(known, np.asarray(yes, float), np.nan)


def _mean_known(*facts) -> np.ndarray:
    """Mean of the known facts per row; unknown (NaN) facts are left out, never counted as yes or no."""
    f = np.vstack(facts)
    n = (~np.isnan(f)).sum(axis=0)
    return np.divide(np.nansum(f, axis=0), n, out=np.full(f.shape[1], np.nan), where=n > 0)


def context_small(layers, post_storm) -> np.ndarray:
    """dark_small context per row of `layers` (inshore_frac, dist_coast_m): outside inshore grounds, 2-25 km
    offshore, first calm pass after a storm (post_storm 1/0, NaN unknown). inshore_frac NaN = no map = unknown."""
    inshore = np.asarray(layers["inshore_frac"], float)
    dist = np.asarray(layers["dist_coast_m"], float)
    storm = np.asarray(post_storm, float)
    p = PARAMS
    return _mean_known(
        _fact(~np.isnan(inshore), inshore < p["inshore_max"]),
        _fact(~np.isnan(dist), (dist >= p["coast_min_m"]) & (dist <= p["coast_max_m"])),
        _fact(~np.isnan(storm), storm == 1),
    )


def context_slowdown(layers, hours) -> np.ndarray:
    """slowdown context per row of `layers` (lane): outside lane cells; slow presence-hours 0.33-3 (shared.md
    issue 3), NaN hours unknown."""
    lane = np.asarray(layers["lane"], bool)
    h = np.asarray(hours, float)
    p = PARAMS
    return _mean_known(
        _fact(np.ones(len(lane), bool), ~lane),
        _fact(~np.isnan(h), (h >= p["slow_hours_min"]) & (h <= p["slow_hours_max"])),
    )


_DETECTORS = ["p_mid", "gi_z", "cusum_s", "context"]


def _ranks(scores: pd.DataFrame) -> pd.DataFrame:
    """Percentile rank of each detector within its event type, over one identical row set (no NaN allowed).
    p_mid is ranked as 1 - p so a small tail value ranks high."""
    if scores[_DETECTORS].isna().any().any():
        raise ValueError("a detector is NaN on some rows; the four ranks must share one row set")
    vals = scores[_DETECTORS].assign(p_mid=1 - scores["p_mid"])
    return vals.groupby(scores["event_type"]).rank(pct=True)


def fuse(scores: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """U = mean of the four percentile ranks; agreement = detectors placing the row in their own top top_frac.
    Agreement counts angles that agree on the same counts, not independent proofs."""
    r = _ranks(scores)
    return r.mean(axis=1).to_numpy(), (r > 1 - PARAMS["top_frac"]).sum(axis=1).to_numpy()


def _slow_hours(m: pd.DataFrame, events: pd.DataFrame) -> np.ndarray:
    """Slow presence-hours per slowdown row: sum of duration_min / 60 over its events; NaN when any duration is
    null (GFW gives none) or the cell-day had no event. TODO(P6): real source of slow hours, question #131."""
    ev = events[events["event_type"] == "slowdown"]
    ev = ev.assign(date=ev["time_utc"].dt.date, h=ev["duration_min"] / 60)
    g = ev.groupby(["cell_id", "date"])["h"]
    hours = g.sum().where(g.count() == g.size()).rename("hours").reset_index()
    keys = m[["cell_id"]].assign(date=pd.to_datetime(m["date"]).dt.date)
    return keys.merge(hours, how="left")["hours"].to_numpy(float)


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


def _weekly_y(m: pd.DataFrame) -> np.ndarray:
    """Each row gets its cell's weekly y = (sum C + 0.5) / (sum mu + 0.5) over the same ISO week as gi_z (#87)."""
    week = pd.to_datetime(m["date"]).dt.to_period("W-SUN")
    sums = (
        m.assign(week=week)
        .groupby(["event_type", "week", "cell_id"])[["count", "mu"]]
        .transform("sum")
    )
    return ((sums["count"] + 0.5) / (sums["mu"] + 0.5)).to_numpy()


def run_cells() -> None:
    """aggregate/observed + forecast/expected -> fuse/cells.parquet, observed rows (E > 0) in the evaluation
    window only. CUSUM runs over all observed history so a build-up before the window still counts."""
    obs = Observed(io.read_stage("aggregate/observed")).observed_rows()
    exp = io.read_stage("forecast/expected")
    # Live forecast only (fold 0, #74 item 6; the simulator writes 0 too, #172). Backtest folds would duplicate
    # cell-days.
    exp = exp[exp["fold"] == 0]
    m = obs.merge(exp, on=_KEY).sort_values(["date", "cell_id"])
    m["cusum_s"] = 0.0
    for _, g in m.groupby(["event_type", "cell_id"]):
        m.loc[g.index, "cusum_s"] = cusum(g["count"], g["mu"], g["phi"])
    T = io.read_snapshot()["T"]
    start = T - timedelta(days=T.weekday() + 21)  # Monday of the ISO week three weeks before T's
    m = m[pd.to_datetime(m["date"]).between(pd.Timestamp(start), pd.Timestamp(T))].reset_index(
        drop=True
    )
    layers = io.read_stage("reference/cells")[["cell_id", "inshore_frac", "lane", "dist_coast_m"]]
    m = m.merge(layers, on="cell_id", how="left")
    # TODO(P6): post_storm is not in coverage/exposure yet (P3 contract #85); unknown until it is.
    post_storm = np.full(len(m), np.nan)
    hours = _slow_hours(m, io.read_stage("match/events"))
    small = (m["event_type"] == "dark_small").to_numpy()
    p_mid = tail_pmid(m["count"], m["mu"], m["phi"])
    scores = m[_KEY].assign(
        p_mid=p_mid,
        bh_flag=bh(p_mid),
        gi_z=_weekly_gi(m),
        cusum_s=m["cusum_s"],
        context=np.where(small, context_small(m, post_storm), context_slowdown(m, hours)),
        y=((m["count"] + 0.5) / (m["mu"] + 0.5)).to_numpy(),  # #87
        y_week=_weekly_y(m),
    )
    scores["U"], scores["agreement"] = fuse(scores)
    io.write_stage("fuse/cells", scores, _provenance("aggregate/observed"))  # type: ignore[arg-type]
