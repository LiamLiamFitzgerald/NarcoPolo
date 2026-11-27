"""P5 forecast: expected counts mu per cell, date and event type, plus dispersion and intervals.

Every function works on one event type at a time. Frames carry cell_id, date, count, exposure.
Fits take a Split and the caller's split.train(frame); they raise on any row at or after the
cutoff, so look-ahead fails loudly instead of quietly improving the backtest (principle 6).
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import statsmodels.api as sm
from scipy import stats

from core.config import load
from core.grid import parent
from core.io import CONFIG_PATH, ROOT, read_snapshot, read_stage, stage_path, write_stage
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
    cols = [
        "intercept",
        "inshore",
        "inshore_missing",
        "lane",
        "log_dist_coast",
        "static_frac",
    ]
    X = c[["cell_id", *cols]].merge(pd.DataFrame({"date": dates}), how="cross")
    if event_type == "slowdown":
        angle = 2 * np.pi * X["date"].dt.day_of_year / 365
        X = X.assign(season_sin=np.sin(angle), season_cos=np.cos(angle))
    return X


def _with_x(rows: pd.DataFrame, X: pd.DataFrame) -> pd.DataFrame:
    return rows.merge(X, on=_ID, how="left")


def _xb(beta: pd.Series, rows: pd.DataFrame) -> pd.Series:
    return rows[beta.index].to_numpy() @ beta.to_numpy()


def _fit_rows(
    split: Split, train10: pd.DataFrame, X10: pd.DataFrame
) -> tuple[pd.DataFrame, list[str]]:
    """Training rows with E > 0 and known covariates, and the columns that can be fitted."""
    split.assert_train(train10)
    rows = _with_x(train10[train10["exposure"] > 0], X10)
    cols = [c for c in X10.columns if c not in _ID]
    rows = rows.dropna(subset=cols)
    # a column with no variation in training (e.g. no missing inshore anywhere) can't be fitted
    return rows, [c for c in cols if c == "intercept" or rows[c].nunique() > 1]


def fit_glm(split: Split, train10: pd.DataFrame, X10: pd.DataFrame) -> tuple[pd.Series, float]:
    """Quasi-Poisson GLM on 10 km rows with E > 0, offset log E. Returns (beta, phi)."""
    rows, cols = _fit_rows(split, train10, X10)
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


def nb2_alpha(split: Split, train10: pd.DataFrame, X10: pd.DataFrame) -> float:
    """NB2 fit on the same rows as fit_glm, as a check: variance = mu + alpha x mu^2.

    alpha near 0 agrees with phi near 1; a large alpha alongside phi near 1 means they disagree.
    """
    rows, cols = _fit_rows(split, train10, X10)
    res = sm.NegativeBinomial(rows["count"], rows[cols], offset=np.log(rows["exposure"])).fit(
        disp=0
    )
    return float(res.params["alpha"])


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
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
    delta: float,
    min_se: float,
    level: float,
) -> pd.DataFrame:
    """Expected rows for split.test of the 2 km frame, fitted on split.train only.

    frames = (fine, coarse, X2, X10) for one event type. The GLM's dispersion is used for the
    EWMA's intervals too: phi describes the data, and the EWMA has no fit of its own to give one.
    """
    f2, f10, X2, X10 = frames
    target = split.test(f2)
    mu_glm, phi = glm_mu(split, split.train(f10), X10, target, X2)
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
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
    delta: float,
    min_se: float,
    level: float,
) -> pd.DataFrame:
    """Production rows (fold = 0) for the evaluation window, fitted only on days before it."""
    return expected_rows(model, evaluation_split(T), 0, frames, delta, min_se, level)


def choose_baseline(
    event_type: str, skills: dict[str, pd.DataFrame], decisions: str, when: str
) -> str:
    """Keep the model with the higher mean backtest skill and append the choice to DECISIONS.md.

    Refuses to choose on NaN or infinite skill, so a broken backtest can't be recorded as a win.
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
    with open(decisions, "a", encoding="utf-8") as f:
        # DECISIONS.md format: YYYY-MM-DD HH:MM · who · decision · why
        f.write(f"{when} · P5 · baseline for {event_type}: {best} · walk-forward skill {ranges}\n")
    return best


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


def _fold_model(
    name: str,
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame],
    fs: list[Split],
    params: tuple[float, float, float],
    store: dict[tuple[str, int], pd.DataFrame],
) -> Callable[[Split], pd.Series]:
    """A backtest model that also keeps each fold's expected rows, so they're computed once."""

    def predict(split: Split) -> pd.Series:
        fold = fs.index(split) + 1
        rows = expected_rows(name, split, fold, frames, *params)
        store[(name, fold)] = rows
        return rows["mu"].set_axis(split.test(frames[0]).index)

    return predict


def forecast_all(
    observed: pd.DataFrame,
    cells: pd.DataFrame,
    T: pd.Timestamp,
    cfg: Mapping[str, Any],
    decisions: str,
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
    for event_type, k in n_folds.items():
        f = observed[observed["event_type"] == event_type]
        f2, f10 = f[f["level"] == 2000], f[f["level"] == 10000]
        dates = pd.DatetimeIndex(sorted(f2["date"].unique()))
        X2 = design_matrix(cells[cells["level"] == 2000], dates, event_type)
        X10 = design_matrix(cells[cells["level"] == 10000], dates, event_type)
        frames = (f2, f10, X2, X10)
        fs = folds(T.date(), k)  # core fixes the 7-day embargo and 7-day test window

        fold_rows: dict[tuple[str, int], pd.DataFrame] = {}
        skills = {
            name: backtest(f2, fs, _fold_model(name, frames, fs, params, fold_rows))
            for name in ("ewma", "glm")
        }
        chosen = (baseline or {}).get(event_type) or _choose_or_default(
            event_type, skills, decisions, when
        )
        window = forecast_window(chosen, T, frames, *params)
        expected += [window, *(fold_rows[(chosen, i)] for i in range(1, k + 1))]

        prod = evaluation_split(T)
        alpha = nb2_alpha(prod, prod.train(f10), X10)
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


def _read_cells() -> pd.DataFrame:
    """Attributes of the cells layer of reference/layers.gpkg, validated by core.io; P5 needs no geometry."""
    return pd.DataFrame(read_stage("reference/cells").drop(columns="geometry"))


def stage(
    T: pd.Timestamp,
    cfg: Mapping[str, Any],
    provenance: Literal["simulated", "real"],
    decisions: str,
    when: str,
    baseline: dict[str, str] | None = None,
) -> tuple[Path, pd.DataFrame]:
    """make all: read aggregate/observed and the cells layer; write forecast/expected.parquet.

    Returns the written path and the backtest report.
    """
    observed = read_stage("aggregate/observed")
    observed["date"] = pd.to_datetime(observed["date"])
    expected, report = forecast_all(observed, _read_cells(), T, cfg, decisions, when, baseline)
    return write_stage("forecast/expected", expected, provenance), report


def _provenance(name: str) -> Literal["simulated", "real"]:
    """Inherit 'simulated' or 'real' from an input stage file's core.io stamp.

    shortcut: reads core.io's parquet metadata key directly; swap for a core.io helper if P1 adds one.
    """
    meta = pq.read_schema(stage_path(name)).metadata or {}
    return json.loads(meta[b"narco"])["provenance"]


def _cfg(cfg: Mapping[str, Any], key: str) -> Any:
    if key not in cfg:
        raise KeyError(f"config.yaml has no {key!r}; P5's keys are listed in issue #69")
    return cfg[key]


def _choose_or_default(
    event_type: str, skills: dict[str, pd.DataFrame], decisions: str, when: str
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
    stage(
        pd.Timestamp(read_snapshot()["T"]),
        cfg,
        _provenance("aggregate/observed"),
        str(ROOT / "DECISIONS.md"),
        when,
    )
