"""P5 forecast: expected counts mu per cell, date and event type, plus dispersion and intervals.

Every function works on one event type at a time. Frames carry cell_id, date, count, exposure.
Fits take a Split and the caller's split.train(frame); they raise on any row at or after the
cutoff, so look-ahead fails loudly instead of quietly improving the backtest (principle 6).
"""

import gc
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from core.config import load
from core.grid import parent
from core.io import (
    CONFIG_PATH,
    ROOT,
    read_cells,
    read_provenance,
    read_snapshot,
    read_stage,
    write_stage,
)
from core.split import Split, folds

_ID = ["cell_id", "date"]


def _decayed_sums(split: Split, train: pd.DataFrame, delta: float) -> pd.DataFrame:
    """S_C and S_E per cell as they stand after cutoff - 1 day; unobserved days add 0 to both."""
    split.assert_train(train)
    age = (pd.Timestamp(split.cutoff) - pd.Timedelta(days=1) - train["date"]).dt.days
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

    Rates are shrunk towards the level above with min_se units of prior exposure (P5 rule for #58,
    DECISIONS.md): r_cell = (S_C + min_se x r_parent) / (S_E + min_se), and the 10 km parent the
    same way towards the region. A thinly seen cell sits near its parent, as the spec intends,
    and a cell with no events yet gets a small rate instead of 0 (which made deviance infinite).
    """
    fine = _decayed_sums(split, train2, delta)
    coarse = _decayed_sums(split, train10, delta)
    region_rate = coarse["s_c"].sum() / coarse["s_e"].sum()
    coarse_rate = _shrink(coarse["s_c"], coarse["s_e"], region_rate, min_se)

    up = _parents(target2["cell_id"]).map(coarse_rate).fillna(region_rate)
    s_c = target2["cell_id"].map(fine["s_c"]).fillna(0.0)
    s_e = target2["cell_id"].map(fine["s_e"]).fillna(0.0)
    return _shrink(s_c, s_e, up, min_se) * target2["exposure"]


def _shrink(s_c: pd.Series, s_e: pd.Series, prior_rate: Any, k: float) -> pd.Series:
    """Rate with k units of prior exposure at prior_rate (a gamma-Poisson posterior mean)."""
    return (s_c + k * prior_rate) / (s_e + k)


def design_matrix(cells: pd.DataFrame, dates: pd.DatetimeIndex, event_type: str) -> pd.DataFrame:
    """Covariates per (cell, date) from reference/layers.gpkg cells (one level at a time).

    inshore_frac NaN (no map) gets a missing flag and 0 in the value column, per the spec.
    Seasonal terms only for slowdowns: 90 days of radar can't estimate a season. static_frac is not a
    covariate (#156): it separated the data (fully static cells never have events) and the fits did not converge.
    """
    c = cells.assign(
        intercept=1.0,
        inshore_missing=cells["inshore_frac"].isna().astype(float),
        inshore=cells["inshore_frac"].fillna(0.0),
        lane=cells["lane"].astype(float),
        log_dist_coast=np.log(cells["dist_coast_m"]),
    )
    cols = [
        "intercept",
        "inshore",
        "inshore_missing",
        "lane",
        "log_dist_coast",
    ]  # no static_frac (#156): masking already removes static areas from detection, and the term separates
    X = c[["cell_id", *cols]].merge(pd.DataFrame({"date": dates}), how="cross")
    if event_type == "slowdown":
        angle = 2 * np.pi * X["date"].dt.day_of_year / 365
        X = X.assign(season_sin=np.sin(angle), season_cos=np.cos(angle))
    return X


def _parents(cell_ids: pd.Series) -> pd.Series:
    """10 km parent per row, computing each distinct cell's parent once (hundreds, not 700k)."""
    unique = pd.unique(cell_ids)
    return cell_ids.map(dict(zip(unique, map(parent, unique))))


def _with_x(rows: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    """Rows with their covariates; forecast_all joins them once, so this is then a no-op."""
    if set(X.columns) <= set(rows.columns):
        return rows
    return rows.merge(X, on=_ID, how="left")


def _xb(beta: pd.Series, rows: pd.DataFrame) -> pd.Series:
    return rows[beta.index].to_numpy() @ beta.to_numpy()


def _fit_rows(
    split: Split, train2: pd.DataFrame, X2: pd.DataFrame
) -> tuple[pd.DataFrame, list[str]]:
    """Training rows with E > 0 and known covariates, and the columns that can be fitted."""
    split.assert_train(train2)
    rows = _with_x(train2[train2["exposure"] > 0], X2)
    cols = [c for c in X2.columns if c not in _ID]
    rows = rows.dropna(subset=cols)
    # a column with no variation in training (e.g. no missing inshore anywhere) can't be fitted
    return rows, [c for c in cols if c == "intercept" or rows[c].nunique() > 1]


def fit_glm(split: Split, train2: pd.DataFrame, X2: pd.DataFrame) -> tuple[pd.Series, float]:
    """Quasi-Poisson GLM on 2 km rows with E > 0, offset log E (#58). Returns (beta, phi)."""
    beta, phi, _ = _fit(split, train2, X2)
    return beta, phi


def _fit(
    split: Split, train2: pd.DataFrame, X2: pd.DataFrame
) -> tuple[pd.Series, float, pd.DataFrame]:
    """fit_glm plus the rows it was fitted on, which empirical Bayes needs again.

    Always a cold start: warm-starting from the previous fold changed mu by up to 21% on the
    simulator (some fits are sensitive to the starting point), so it was tried and dropped.
    """
    rows, cols = _fit_rows(split, train2, X2)
    # Each IRLS step leaves ~400 MB of cyclic garbage on ~700k rows; few Python objects are made, so the default
    # collector never runs mid-fit and memory passed 6 GB. Collect every generation often while fitting only.
    old = gc.get_threshold()
    gc.set_threshold(100, 1, 1)
    try:
        res = sm.GLM(
            rows["count"].to_numpy(),
            rows[cols].to_numpy(),
            family=sm.families.Poisson(),
            offset=np.log(rows["exposure"].to_numpy()),
        ).fit(scale="X2")
    finally:
        gc.set_threshold(*old)
        gc.collect()
    if not res.converged:
        # e.g. a covariate whose cells never have events (fully static cells): its coefficient
        # runs off towards -inf; say so rather than use an unconverged fit silently (#156)
        warnings.warn(
            f"GLM did not converge for cutoff {split.cutoff} ({len(rows)} rows, columns {cols})",
            stacklevel=2,
        )
    return pd.Series(res.params, index=cols), float(res.scale), rows


def empirical_bayes(O: pd.Series, M: pd.Series) -> pd.Series:
    """Shrunk multiplier per 10 km cell: (a + O) / (a + M); 1 everywhere if there's no extra variation."""
    denom = ((O - M) ** 2 - M).sum()
    if denom <= 0:
        return pd.Series(1.0, index=O.index)
    a = (M**2).sum() / denom
    return (a + O) / (a + M)


def nb2_alpha(split: Split, train2: pd.DataFrame, X2: pd.DataFrame) -> float:
    """NB2 fit on the same rows as fit_glm, as a check: variance = mu + alpha x mu^2.

    alpha near 0 agrees with phi near 1; a large alpha alongside phi near 1 means they disagree.
    """
    rows, cols = _fit_rows(split, train2, X2)
    res = sm.NegativeBinomial(rows["count"], rows[cols], offset=np.log(rows["exposure"])).fit(
        disp=0
    )
    return float(res.params["alpha"])


def predict_glm(beta: pd.Series, theta: pd.Series, rows2: pd.DataFrame) -> pd.Series:
    """mu = E x exp(x beta, fine cell's own covariates) x theta of its 10 km parent.

    A row with a missing covariate gets mu = NaN: unknown, never filled with zero.
    """
    t = _parents(rows2["cell_id"]).map(theta).fillna(1.0)
    return rows2["exposure"] * np.exp(_xb(beta, rows2)) * t


def glm_mu(
    split: Split,
    train2: pd.DataFrame,
    target2: pd.DataFrame,
    X2: pd.DataFrame,
) -> tuple[pd.Series, float]:
    """Fit on 2 km, shrink per 10 km cell, predict the 2 km target rows. Returns (mu, phi)."""
    # O and M over the fit's own rows: a row with an unknown covariate has no M, so no O either
    beta, phi, seen = _fit(split, train2, X2)
    seen = seen.assign(m=seen["exposure"] * np.exp(_xb(beta, seen)))
    # O and M per 10 km cell, summed over its 2 km children
    totals = seen.groupby(_parents(seen["cell_id"]))[["count", "m"]].sum()
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


EXPECTED_COLUMNS = [
    "cell_id",
    "date",
    "event_type",
    "mu",
    "phi",
    "lo90",
    "hi90",
    "model",
    "fold",
]


def expected_rows(
    model: str,
    split: Split,
    fold: int,
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    delta: float,
    min_se: float,
    level: float,
    glm: tuple[pd.Series, float] | None = None,
) -> pd.DataFrame:
    """Expected rows for split.test of the 2 km frame, fitted on split.train only.

    frames = (fine, coarse, X2) for one event type. The GLM's dispersion is used for the
    EWMA's intervals too: phi describes the data, and the EWMA has no fit of its own to give one.
    glm: this fold's (mu, phi) from glm_mu if already computed, so it isn't fitted twice.
    """
    f2, f10, X2 = frames
    target = split.test(f2)
    mu_glm, phi = glm or glm_mu(split, split.train(f2), target, X2)
    if model == "ewma":
        mu = ewma(split, split.train(f2), split.train(f10), target, delta, min_se)
    elif model == "glm":
        mu = mu_glm
    else:
        raise ValueError(f"unknown model {model!r}")
    lo, hi = nb_interval(mu, phi, level)
    out = target[["cell_id", "date", "event_type"]].assign(
        mu=mu, phi=phi, lo90=lo, hi90=hi, model=model, fold=fold
    )
    return out[EXPECTED_COLUMNS].reset_index(drop=True)


def evaluation_split(T: pd.Timestamp) -> Split:
    """The scored window: Monday of the ISO week 3 weeks before T's week, up to T (22-28 days).

    No embargo: the production fit uses every day before the window and none inside it.
    """
    start = T.normalize() - pd.Timedelta(days=T.weekday() + 21)
    return Split(start.date(), embargo_days=0, test_days=(T.normalize() - start).days + 1)


def forecast_window(
    model: str,
    T: pd.Timestamp,
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    delta: float,
    min_se: float,
    level: float,
) -> pd.DataFrame:
    """Production rows (fold = 0) for the evaluation window, fitted only on days before it."""
    return expected_rows(model, evaluation_split(T), 0, frames, delta, min_se, level)


def choose_baseline(
    event_type: str, skills: dict[str, pd.DataFrame], decisions: str | None, when: str
) -> str:
    """Keep the model with the higher mean backtest skill and append the choice to DECISIONS.md.

    Refuses to choose on NaN or infinite skill, so a broken backtest can't be recorded as a win.
    decisions=None records nothing (simulator runs); a choice equal to the last one P5 recorded
    for this event type isn't written again, so repeated runs don't fill the log.
    """
    means = {name: t["skill"].mean() for name, t in skills.items()}
    bad = [n for n, t in skills.items() if not np.isfinite(t["skill"]).all()]
    if bad:
        raise ValueError(f"non-finite backtest skill for {bad}; not choosing a baseline")
    best = max(means, key=means.__getitem__)
    ranges = "; ".join(
        f"{n}: mean {means[n]:.3f}, range {t['skill'].min():.3f} to {t['skill'].max():.3f}"
        for n, t in skills.items()
    )
    if decisions is None or _last_choice(decisions, event_type) == best:
        return best
    with open(decisions, "a", encoding="utf-8") as f:
        # DECISIONS.md format: YYYY-MM-DD HH:MM · who · decision · why
        f.write(f"{when} · P5 · {_TAG}{event_type}: {best} · walk-forward skill {ranges}\n")
    return best


_TAG = "baseline for "


def _last_choice(decisions: str, event_type: str) -> str | None:
    """The model in the last line P5 wrote for this event type, if any."""
    mark = f" · P5 · {_TAG}{event_type}: "
    path = Path(decisions)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    last = [ln for ln in lines if mark in ln][-1:]
    return last[0].split(mark)[1].split(" · ")[0] if last else None


def backtest(
    frame2: pd.DataFrame,
    folds: list[Split],
    model: Callable[[Split], pd.Series],
    prior_exposure: float,
) -> pd.DataFrame:
    """Walk-forward skill per fold: 1 - D_model / D_flat on observed test rows (E > 0).

    model(split) returns mu for split.test(frame2). Flat = each cell's training-average rate x E,
    shrunk towards the region rate with the same prior exposure as the EWMA, so neither side
    gets an infinite deviance from a rate of exactly 0 (#58).
    A fold with no observed test rows (no calm pass that week) has no skill and is left out.
    """
    out = []
    for k, split in enumerate(folds, start=1):
        test = split.test(frame2)
        mu = model(split)
        keep = test["exposure"] > 0
        if not keep.any():
            continue
        train = split.train(frame2)
        sums = train.groupby("cell_id")[["count", "exposure"]].sum()
        region = sums["count"].sum() / sums["exposure"].sum()
        cell_rate = _shrink(sums["count"], sums["exposure"], region, prior_exposure)
        flat = test["cell_id"].map(cell_rate).fillna(region) * test["exposure"]
        d_model = poisson_deviance(test["count"][keep], mu[keep])
        d_flat = poisson_deviance(test["count"][keep], flat[keep])
        out.append({"fold": k, "skill": 1 - d_model / d_flat})
    return pd.DataFrame(out)


def _fold_model(
    name: str,
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame],
    fs: list[Split],
    params: tuple[float, float, float],
    store: dict[tuple[str, int], pd.DataFrame],
    glm_fits: dict[int, tuple[pd.Series, float]],
) -> Callable[[Split], pd.Series]:
    """A backtest model that keeps each fold's expected rows and GLM fit, so each is made once."""

    def predict(split: Split) -> pd.Series:
        fold = fs.index(split) + 1
        if fold not in glm_fits:
            f2, _, X2 = frames
            glm_fits[fold] = glm_mu(split, split.train(f2), split.test(f2), X2)
        rows = expected_rows(name, split, fold, frames, *params, glm=glm_fits[fold])
        store[(name, fold)] = rows
        return rows["mu"].set_axis(split.test(frames[0]).index)

    return predict


def forecast_all(
    observed: pd.DataFrame,
    cells: pd.DataFrame,
    T: pd.Timestamp,
    cfg: Mapping[str, Any],
    decisions: str | None,
    when: str,
    baseline: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The whole forecast stage for both event types. Returns (expected rows, report).

    expected: fold 0 (evaluation window) plus every backtest fold, all from the chosen model.
    report: per type and model, backtest skill mean/min/max, phi and the NB2 alpha check.
    baseline forces a model per type (skips choose_baseline), e.g. while backtest skill is broken.
    cfg is the full config: split.n_folds_* plus P5's ewma_delta, ewma_min_se and interval.
    """
    n_folds = {
        "slowdown": cfg["split"]["n_folds_slowdown"],
        "dark_small": cfg["split"]["n_folds_small"],
    }
    params = (_cfg(cfg, "ewma_delta"), _cfg(cfg, "ewma_min_se"), _cfg(cfg, "interval"))
    expected, report = [], []
    observed = observed.assign(date=pd.to_datetime(observed["date"]))  # core may give plain dates
    for event_type, k in n_folds.items():
        f = observed[observed["event_type"] == event_type]
        f2, f10 = f[f["level"] == 2000], f[f["level"] == 10000]
        dates = pd.DatetimeIndex(sorted(f2["date"].unique()))
        X2 = design_matrix(cells[cells["level"] == 2000], dates, event_type)
        f2 = f2.merge(X2, on=_ID, how="left")  # covariates joined once, not in every fold
        frames = (f2, f10, X2)
        fs = folds(T.date(), k)  # core fixes the 7-day embargo and 7-day test window

        fold_rows: dict[tuple[str, int], pd.DataFrame] = {}
        glm_fits: dict[int, tuple[pd.Series, float]] = {}
        skills = {
            name: backtest(
                f2, fs, _fold_model(name, frames, fs, params, fold_rows, glm_fits), params[1]
            )
            for name in ("ewma", "glm")
        }
        chosen = (baseline or {}).get(event_type) or _choose_or_default(
            event_type, skills, decisions, when
        )
        window = forecast_window(chosen, T, frames, *params)
        expected += [window, *(fold_rows[(chosen, i)] for i in range(1, k + 1))]

        prod = evaluation_split(T)
        alpha = nb2_alpha(prod, prod.train(f2), X2)
        for name, table in skills.items():
            report.append(
                {
                    "event_type": event_type,
                    "model": name,
                    "chosen": name == chosen,
                    "skill_mean": table["skill"].mean(),
                    "skill_min": table["skill"].min(),
                    "skill_max": table["skill"].max(),
                    "phi": window["phi"].iloc[0],
                    "nb2_alpha": alpha,
                }
            )
    return pd.concat(expected, ignore_index=True), pd.DataFrame(report)


def stage(
    T: pd.Timestamp,
    cfg: Mapping[str, Any],
    provenance: Literal["simulated", "real"],
    decisions: str | None,
    when: str,
    baseline: dict[str, str] | None = None,
) -> tuple[Path, pd.DataFrame]:
    """make all: read aggregate/observed and the cells layer; write forecast/expected.parquet.

    Returns the written path and the backtest report.
    """
    observed = read_stage("aggregate/observed")
    observed["date"] = pd.to_datetime(observed["date"])
    expected, report = forecast_all(observed, read_cells(), T, cfg, decisions, when, baseline)
    return write_stage("forecast/expected", expected, provenance), report


def _cfg(cfg: Mapping[str, Any], key: str) -> Any:
    if key not in cfg:
        raise KeyError(f"config.yaml has no {key!r}; P5's keys are listed in issue #69")
    return cfg[key]


def _choose_or_default(
    event_type: str, skills: dict[str, pd.DataFrame], decisions: str | None, when: str
) -> str:
    """choose_baseline, or EWMA (the spec's "build first" baseline) while skill is undefined (#58).

    Nothing is written to DECISIONS.md in the fallback: no comparison was made.
    """
    try:
        return choose_baseline(event_type, skills, decisions, when)
    except ValueError as e:
        print(f"forecast: {e}; using ewma for {event_type} until #58 is fixed")
        return "ewma"


def run() -> None:
    """make all entry point: reads aggregate/observed and the cells layer, writes forecast/expected."""
    cfg, _ = load(CONFIG_PATH)
    when = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M")
    provenance = read_provenance("aggregate/observed")
    # a choice made on simulated data isn't a team decision, so only real runs are recorded
    decisions = str(ROOT / "DECISIONS.md") if provenance == "real" else None
    stage(pd.Timestamp(read_snapshot()["T"]), cfg, provenance, decisions, when)
