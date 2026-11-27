"""P5 forecast: expected counts mu per cell, date and event type, plus dispersion and intervals.

Every function works on one event type at a time. Frames carry cell_id, date, count, exposure.
Fits take a Split and the caller's split.train(frame); they raise on any row at or after the
cutoff, so look-ahead fails loudly instead of quietly improving the backtest (principle 6).
"""

from collections.abc import Callable

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from forecast._stand_in import Split, parent

_ID = ["cell_id", "date"]


def _decayed_sums(split: Split, train: pd.DataFrame, delta: float) -> pd.DataFrame:
    """S_C and S_E per cell as they stand after cutoff - 1 day; unobserved days add 0 to both."""
    split.assert_train(train)
    age = (split.cutoff - pd.Timedelta(days=1) - train["date"]).dt.days
    w = delta**age
    sums = train.assign(s_c=train["count"] * w, s_e=train["exposure"] * w)
    return sums.groupby("cell_id")[["s_c", "s_e"]].sum()


def ewma(
    split: Split,
    train2: pd.DataFrame,
    train10: pd.DataFrame,
    target2: pd.DataFrame,
    delta: float,
    min_se: float,
) -> pd.Series:
    """Exposure-aware EWMA frozen at the cutoff (A7): mu = r_hat x E for each target row.

    Until a fine cell's S_E reaches min_se, its 10 km parent's rate is used (not divided by 25).
    """
    fine = _decayed_sums(split, train2, delta)
    coarse = _decayed_sums(split, train10, delta)
    coarse_rate = coarse["s_c"] / coarse["s_e"]
    # shortcut: a parent never imaged in training falls back to the region-wide rate; ask P1 if
    # the spec should say something else
    region_rate = coarse["s_c"].sum() / coarse["s_e"].sum()

    se = target2["cell_id"].map(fine["s_e"]).fillna(0.0)
    own = target2["cell_id"].map(fine["s_c"] / fine["s_e"])
    from_parent = target2["cell_id"].map(parent).map(coarse_rate).fillna(region_rate)
    rate = own.where(se >= min_se, from_parent)
    return rate * target2["exposure"]


def design_matrix(cells: pd.DataFrame, dates: pd.DatetimeIndex, event_type: str) -> pd.DataFrame:
    """Covariates per (cell, date) from reference/layers.gpkg cells (one level at a time).

    inshore_frac NaN (no map) gets a missing flag and 0 in the value column, per the spec.
    Seasonal terms only for slowdowns: 90 days of radar can't estimate a season.
    """
    c = cells.assign(
        intercept=1.0,
        inshore_missing=cells["inshore_frac"].isna().astype(float),
        inshore=cells["inshore_frac"].fillna(0.0),
        lane=cells["lane"].astype(float),
        log_dist_coast=np.log(cells["dist_coast_m"]),
    )
    cols = ["intercept", "inshore", "inshore_missing", "lane", "log_dist_coast", "static_frac"]
    X = c[["cell_id", *cols]].merge(pd.DataFrame({"date": dates}), how="cross")
    if event_type == "slowdown":
        angle = 2 * np.pi * X["date"].dt.day_of_year / 365
        X = X.assign(season_sin=np.sin(angle), season_cos=np.cos(angle))
    return X


def _with_x(rows: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    return rows.merge(X, on=_ID, how="left")


def _xb(beta: pd.Series, rows: pd.DataFrame) -> pd.Series:
    return rows[beta.index].to_numpy() @ beta.to_numpy()


def fit_glm(split: Split, train10: pd.DataFrame, X10: pd.DataFrame) -> tuple[pd.Series, float]:
    """Quasi-Poisson GLM on 10 km rows with E > 0, offset log E. Returns (beta, phi)."""
    split.assert_train(train10)
    rows = _with_x(train10[train10["exposure"] > 0], X10)
    cols = [c for c in X10.columns if c not in _ID]
    rows = rows.dropna(subset=cols)
    # a column with no variation in training (e.g. no missing inshore anywhere) can't be fitted
    cols = [c for c in cols if c == "intercept" or rows[c].nunique() > 1]
    res = sm.GLM(
        rows["count"],
        rows[cols],
        family=sm.families.Poisson(),
        offset=np.log(rows["exposure"]),
    ).fit(scale="X2")
    return res.params, float(res.scale)


def empirical_bayes(O: pd.Series, M: pd.Series) -> pd.Series:
    """Shrunk multiplier per 10 km cell: (a + O) / (a + M); 1 everywhere if there's no extra variation."""
    denom = ((O - M) ** 2 - M).sum()
    if denom <= 0:
        return pd.Series(1.0, index=O.index)
    a = (M**2).sum() / denom
    return (a + O) / (a + M)


def predict_glm(beta: pd.Series, theta: pd.Series, rows2: pd.DataFrame) -> pd.Series:
    """mu = E x exp(x beta, fine cell's own covariates) x theta of its 10 km parent.

    A row with a missing covariate gets mu = NaN: unknown, never filled with zero.
    """
    t = rows2["cell_id"].map(parent).map(theta).fillna(1.0)
    return rows2["exposure"] * np.exp(_xb(beta, rows2)) * t


def glm_mu(
    split: Split,
    train10: pd.DataFrame,
    X10: pd.DataFrame,
    target2: pd.DataFrame,
    X2: pd.DataFrame,
) -> tuple[pd.Series, float]:
    """Fit on 10 km, shrink per 10 km cell, predict the 2 km target rows. Returns (mu, phi)."""
    beta, phi = fit_glm(split, train10, X10)
    seen = _with_x(train10[train10["exposure"] > 0], X10)
    seen = seen.assign(m=seen["exposure"] * np.exp(_xb(beta, seen)))
    totals = seen.groupby("cell_id")[["count", "m"]].sum()
    theta = empirical_bayes(totals["count"], totals["m"])
    return predict_glm(beta, theta, _with_x(target2, X2)).set_axis(target2.index), phi


def nb_interval(mu: pd.Series, phi: float, level: float) -> tuple[np.ndarray, np.ndarray]:
    """Central interval from a negative binomial with variance phi x mu; Poisson if phi <= 1."""
    lo_q, hi_q = (1 - level) / 2, 1 - (1 - level) / 2
    m = np.asarray(mu, dtype=float)
    if phi > 1:
        dist = stats.nbinom(np.maximum(m, 1e-12) / (phi - 1), 1 / phi)
    else:
        dist = stats.poisson(m)
    lo, hi = dist.ppf(lo_q), dist.ppf(hi_q)
    zero = m == 0
    return np.where(zero, 0.0, lo), np.where(zero, 0.0, hi)


def poisson_deviance(C: pd.Series, mu: pd.Series) -> float:
    """Mean Poisson deviance; soft counts allowed. A C = 0 row contributes 2 mu."""
    c, m = np.asarray(C, dtype=float), np.asarray(mu, dtype=float)
    pos = c > 0
    log_ratio = np.log(np.where(pos, c, 1.0) / np.where(pos, m, 1.0))
    term = np.where(pos, c * log_ratio, 0.0) - (c - m)
    return float(np.mean(2 * term))


def backtest(
    frame2: pd.DataFrame,
    folds: list[Split],
    model: Callable[[Split], pd.Series],
) -> pd.DataFrame:
    """Walk-forward skill per fold: 1 - D_model / D_flat on observed test rows (E > 0).

    model(split) returns mu for split.test(frame2). Flat = each cell's training-average rate x E.
    """
    out = []
    for k, split in enumerate(folds, start=1):
        test = split.test(frame2)
        mu = model(split)
        keep = test["exposure"] > 0
        train = split.train(frame2)
        sums = train.groupby("cell_id")[["count", "exposure"]].sum()
        region = sums["count"].sum() / sums["exposure"].sum()
        cell_rate = (sums["count"] / sums["exposure"]).replace([np.inf], np.nan)
        flat = test["cell_id"].map(cell_rate).fillna(region) * test["exposure"]
        d_model = poisson_deviance(test["count"][keep], mu[keep])
        d_flat = poisson_deviance(test["count"][keep], flat[keep])
        out.append({"fold": k, "skill": 1 - d_model / d_flat})
    return pd.DataFrame(out)
