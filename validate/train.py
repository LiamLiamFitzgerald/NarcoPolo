"""L4 fitting (docs/learning.md): the site model ladder, fitted offline on simulator labels only.

Rows are site-weeks (one 2 km cell, one ISO week) from the simulator's train regimes; the label is a planted drop in
that cell that week. Features are the merged agents' weekly scores. Rung 0 is the statistics alone, rung 1 a
non-negative logistic stack, rung 2 a monotone Neural Additive Model. A rung replaces the one below only if it wins on
the held-out regimes (L4 step 4). Scores are for sea cells; no vessel identity is read or written.

Two-level time split (L4 step 2). Level 1: the agent scores here use no fitted parameters and only past weeks
(CUSUM), so they are out-of-time by construction; they stand in for validate.signals (#153) until it is on
integration. Level 2: the stack is fitted only on weeks that end before the cutoff of the earliest of the
`n_folds_small` walk-forward folds, and scored only from that cutoff plus `split.embargo_days`.
"""

import json
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

from core import io
from core.config import Config, load
from core.split import Split, folds
from fuse.features import AGENTS as _AGENTS
from fuse.features import _midp  # noqa: F401  (validate/tests/test_train.py checks it)
from fuse.features import weekly_scores as _scores

# TODO(P1): move to config.yaml learn.train (#158); 500, 5 and 2 are docs/learning.md L4 steps 3-4
_DEFAULTS: dict[str, float] = {
    "l2": 1.0,
    "n_eff_min": 500,
    "pos_mult": 5,
    "promote_se": 2,
    "nam_hidden": 32,
    "nam_epochs": 300,
    "nam_lr": 0.01,
    "nam_l2": 0.001,
}


def model_path() -> Path:
    return Path(os.environ.get("NARCO_DATA", io.ROOT / "data")) / "models" / "site_model.json"


def _params(cfg: Config) -> dict[str, float]:
    return {**_DEFAULTS, **cfg["learn"].get("train", {})}


# ---------------------------------------------------------------- rows: site-weeks from the simulator


@contextmanager
def _scratch() -> Iterator[None]:
    """Simulate into a temporary data root, so the user's data/ and raw/ are never overwritten."""
    keys = ("NARCO_DATA", "NARCO_RAW")
    old = {k: os.environ.get(k) for k in keys}
    with tempfile.TemporaryDirectory() as d:
        os.environ["NARCO_DATA"], os.environ["NARCO_RAW"] = f"{d}/data", f"{d}/raw"
        try:
            yield
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def _simulate(cfg: Config, seed: int, regime: str) -> None:
    # tach-ignore(validate runs the simulator; tach.toml change requested in #158)
    from sim.simulate import simulate

    simulate(cfg, seed, regime)  # NotImplementedError for regimes #150 has not built yet


def _labels(rows: pd.DataFrame, truth: pd.DataFrame) -> pd.Series:
    """True where an (active) planted drop fell in that cell during that week."""
    drops = truth[truth["kind"] == "drop"]
    if "active" in drops.columns:  # L1 (#150)
        drops = drops[drops["active"].astype(bool)]
    t = pd.to_datetime(drops["time_utc"], utc=True).dt.tz_convert(None)
    sunday = (t + pd.to_timedelta(6 - t.dt.day_of_week, unit="D")).dt.normalize()
    hit = set(zip(drops["cell_id"], sunday, strict=True))
    keys = zip(rows["cell_id"], pd.to_datetime(rows["date"]), strict=True)
    return pd.Series([k in hit for k in keys], index=rows.index)


def _split(cfg: Config, T: Any) -> Split:
    s = cfg["split"]
    return Split(folds(T, s["n_folds_small"])[-1].cutoff, s["embargo_days"], s["test_days"])


def _site_weeks(cfg: Config, regime: str, seed: int) -> tuple[pd.DataFrame, Split]:
    """Simulate one season; its site-weeks with agent scores and labels, and its level-2 split."""
    with _scratch():
        _simulate(cfg, seed, regime)
        rows = _scores(io.read_stage("aggregate/observed"), io.read_stage("forecast/expected"))
        rows["label"] = _labels(rows, pd.read_parquet(io.truth_path()))
        T = io.read_snapshot()["T"]
    return rows.assign(regime=regime, seed=seed), _split(cfg, T)


def _train(rows: pd.DataFrame, split: Split) -> pd.DataFrame:
    """Level-2 training rows: weeks that end before the cutoff."""
    out = split.train(rows)
    split.assert_train(out)
    return out


def _scored(rows: pd.DataFrame, split: Split) -> pd.DataFrame:
    """Level-2 scoring rows: from the cutoff plus the embargo to the end of the season."""
    lo = pd.Timestamp(split.cutoff) + pd.Timedelta(days=split.embargo_days)
    return pd.DataFrame(rows[pd.to_datetime(rows["date"]) >= lo])


# ---------------------------------------------------------------- rungs


def _standardise(X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sd = X.std(0)
    return X.mean(0), np.where(sd > 0, sd, 1.0)


def _fit_stack(X: np.ndarray, y: np.ndarray, p: Mapping[str, float]) -> tuple[np.ndarray, float]:
    """Rung 1: ridge logistic regression with every weight >= 0, fitted on standardised features and returned on
    the raw feature scale, so p = sigmoid(intercept + sum w x) never falls when a score rises."""
    mean, sd = _standardise(X)
    Z, m = (X - mean) / sd, X.shape[1]

    def loss(th: np.ndarray) -> tuple[float, np.ndarray]:
        z = th[0] + Z @ th[1:]
        r = expit(z) - y
        val = np.sum(np.logaddexp(0, z) - y * z) + 0.5 * p["l2"] * th[1:] @ th[1:]
        return float(val), np.r_[r.sum(), Z.T @ r + p["l2"] * th[1:]]

    bounds = [(None, None)] + [(0.0, None)] * m
    th = minimize(loss, np.zeros(m + 1), jac=True, method="L-BFGS-B", bounds=bounds).x
    w = th[1:] / sd
    return w, float(th[0] - np.sum(w * mean))


def _nam_logit(net: Mapping[str, Any], Z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    pre = Z[:, :, None] * net["u"] + net["c"]
    return net["b"] + (np.maximum(pre, 0) * net["a"]).sum((1, 2)), pre


def _fit_nam(X: np.ndarray, y: np.ndarray, p: Mapping[str, float], seed: int) -> dict[str, Any]:
    """Rung 2: Neural Additive Model, one ReLU net per score, summed into a logit. Input and output weights are
    kept >= 0 (projected after each Adam step), so each shape curve, and p, rises with its score."""
    mean, sd = _standardise(X)
    Z, (n, m), H = (X - mean) / sd, X.shape, int(p["nam_hidden"])
    rng = np.random.default_rng(seed)
    rate = float(np.clip(y.mean(), 1 / (n + 1), n / (n + 1)))
    net: dict[str, Any] = {
        "u": np.abs(rng.normal(size=(m, H))),
        "c": rng.normal(size=(m, H)),
        "a": np.abs(rng.normal(size=(m, H))) / H,
        "b": np.array(np.log(rate / (1 - rate))),
    }
    mom = {k: np.zeros_like(v) for k, v in net.items()}
    var = {k: np.zeros_like(v) for k, v in net.items()}
    for t in range(1, int(p["nam_epochs"]) + 1):
        z, pre = _nam_logit(net, Z)
        r = (expit(z) - y) / n
        dpre = r[:, None, None] * net["a"] * (pre > 0)
        grad = {
            "u": (dpre * Z[:, :, None]).sum(0) + p["nam_l2"] * net["u"],
            "c": dpre.sum(0),
            "a": (r[:, None, None] * np.maximum(pre, 0)).sum(0) + p["nam_l2"] * net["a"],
            "b": np.array(r.sum()),
        }
        for k, g in grad.items():  # Adam with its usual betas
            mom[k] = 0.9 * mom[k] + 0.1 * g
            var[k] = 0.999 * var[k] + 0.001 * g**2
            net[k] = net[k] - p["nam_lr"] * (mom[k] / (1 - 0.9**t)) / (
                np.sqrt(var[k] / (1 - 0.999**t)) + 1e-8
            )
        net["u"], net["a"] = np.maximum(net["u"], 0), np.maximum(net["a"], 0)
    return {**net, "b": float(net["b"]), "mean": mean, "sd": sd}


def _fit(
    rung: int, X: np.ndarray, y: np.ndarray, p: Mapping[str, float], seed: int
) -> dict[str, Any]:
    if rung == 1:
        w, b = _fit_stack(X, y, p)
        return {"rung": 1, "w": w, "b": b}
    return {"rung": 2, **_fit_nam(X, y, p, seed)}


def _predict(fit: Mapping[str, Any], X: np.ndarray, midp: np.ndarray) -> np.ndarray:
    """p_site in 0-1. Rung 0 stands in for 1 - p_comb (L3 is P6's, #152) with the mid-p agent alone."""
    if fit["rung"] == 0:
        return 1 - 10.0 ** (-midp)
    if fit["rung"] == 1:
        return expit(fit["b"] + X @ fit["w"])
    return expit(_nam_logit(fit, (X - fit["mean"]) / fit["sd"])[0])


# ---------------------------------------------------------------- evaluation and the ladder


def _evaluate(
    fit: Mapping[str, Any],
    frames: Sequence[tuple[pd.DataFrame, Split]],
    features: list[str],
    k: int,
) -> dict[str, list[float]]:
    """Per season (regime x seed) on its scored weeks: mean precision@k over weeks, and the Brier score."""
    prec, brier = [], []
    for rows, split in frames:
        s = _scored(rows, split).sort_values(["date", "cell_id"], ignore_index=True)
        s["p"] = _predict(fit, s[features].to_numpy(float), s["midp"].to_numpy(float))
        top = (
            s.sort_values(["date", "p"], ascending=[True, False], kind="stable")
            .groupby("date")
            .head(k)
        )
        prec.append(float(top.groupby("date")["label"].sum().mean() / k))
        brier.append(float(np.mean((s["p"] - s["label"]) ** 2)))
    return {"precision_at_k": prec, "brier": brier}


def _promote(cand: Mapping[str, Any], cur: Mapping[str, Any], n_se: float) -> dict[str, Any]:
    """L4 step 4: mean held-out precision@k gain > n_se x its SE across seasons, and Brier no worse."""
    d = np.subtract(cand["precision_at_k"], cur["precision_at_k"])
    se = float(d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 else float("inf")
    gain = float(d.mean())
    db = float(np.mean(cand["brier"]) - np.mean(cur["brier"]))
    return {"gain": gain, "se": se, "brier_change": db, "promoted": gain > n_se * se and db <= 0}


def _plain(x: Any) -> Any:
    """JSON-safe: numpy to Python, non-finite floats to None."""
    if isinstance(x, dict):
        return {str(k): _plain(v) for k, v in x.items()}
    if isinstance(x, list | tuple | np.ndarray):
        return [_plain(v) for v in x]
    if isinstance(x, bool | np.bool_):
        return bool(x)
    if isinstance(x, int | np.integer):
        return int(x)
    if isinstance(x, float | np.floating):
        return float(x) if np.isfinite(x) else None
    return x


def _weights(fit: Mapping[str, Any], features: list[str]) -> dict[str, Any]:
    """R4: rung 1 weights are a list in `features` order; higher rungs keep their nets under `params`."""
    if fit["rung"] == 0:
        return {"weights": [], "intercept": 0.0}
    if fit["rung"] == 1:
        return {"weights": list(fit["w"]), "intercept": fit["b"]}
    params = {
        f: {"mean": fit["mean"][j], "sd": fit["sd"][j], **{k: fit[k][j] for k in ("u", "c", "a")}}
        for j, f in enumerate(features)
    }
    return {"weights": [], "intercept": fit["b"], "params": params}


def _features(cfg: Config) -> list[str]:
    """One feature per merged agent: the first of each group in reports/signals.json (L2, #153) if it exists,
    else the config's agent list; only agents scored here."""
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "signals.json"
    if path.exists():
        groups = json.loads(path.read_text())["merged"]
    else:
        groups = [[a] for a in cfg["learn"]["agents"]]
    return [g[0] for g in groups if g[0] in _AGENTS]


def _ladder(
    train: Sequence[tuple[pd.DataFrame, Split]],
    held: Sequence[tuple[pd.DataFrame, Split]],
    features: list[str],
    p: Mapping[str, float],
    k: int,
    seed: int,
) -> dict[str, Any]:
    """Fit rung 1 (and rung 2 when n_eff allows) on level-2 training rows; keep each only if it beats the best
    rung below on the held-out seasons; ablate the winner."""
    rows = pd.concat([_train(r, s) for r, s in train], ignore_index=True)
    X, y = rows[features].to_numpy(float), rows["label"].to_numpy(float)
    n, pos = len(y), int(y.sum())
    n_eff = min(n, int(p["pos_mult"]) * pos)
    rungs = [1, 2] if n_eff >= p["n_eff_min"] else [1]  # L4 step 3
    if not held:
        rungs = []  # held-out regimes decide promotion; with none, the statistics alone stay

    best: dict[str, Any] = {"rung": 0}
    ev = {0: _evaluate(best, held, features, k)} if held else {}
    steps = []
    for rung in rungs:
        fit = _fit(rung, X, y, p, seed)
        ev[rung] = _evaluate(fit, held, features, k)
        step = _promote(ev[rung], ev[best["rung"]], p["promote_se"])
        steps.append({"rung": rung, "against": best["rung"], **step})
        if step["promoted"]:
            best = fit

    ablation = {}
    if best["rung"] > 0:  # L4 step 5: refit without each agent
        for j, f in enumerate(features):
            keep = [g for g in features if g != f]
            sub = _fit(best["rung"], np.delete(X, j, axis=1), y, p, seed) if keep else {"rung": 0}
            a = _promote(_evaluate(sub, held, keep, k), ev[best["rung"]], p["promote_se"])
            ablation[f] = {
                "gain_without": a["gain"],
                "se": a["se"],
                "changes_nothing": abs(a["gain"]) <= a["se"],
            }

    try:
        import lightgbm  # noqa: F401  # pyright: ignore[reportMissingImports]

        lgbm = "installed, rung 2' not fitted yet: TODO(P1)"
    except ImportError:
        lgbm = "skipped: lightgbm is not installed (no new dependencies)"
    held_out = {
        str(r): {"precision_at_k": np.mean(e["precision_at_k"]), "brier": np.mean(e["brier"])}
        for r, e in ev.items()
    }
    return {
        "rung": best["rung"],
        "features": features,
        **_weights(best, features),
        "metrics": {
            "n": n,
            "n_positive": pos,
            "n_eff": n_eff,
            "rungs_tried": rungs,
            "held_out": held_out,
            "promotion": steps,
            "ablation": ablation,
            "lightgbm": lgbm,
        },
    }


def fit_site_model(regimes: list[str], seeds: list[int]) -> dict[str, Any]:
    """Fit the L4 ladder on the simulator and write <data root>/models/site_model.json; returns what it wrote.

    regimes: the train regimes; promotion is decided on config learn.regimes.held_out (minus any trained on).
    A held-out regime the simulator cannot build yet (#150) is skipped and listed in metrics; with none left,
    no rung is promoted and the file says rung 0. Applying it (P6, fuse.learn), with x = scores in `features`:
    rung 1: p_site = sigmoid(intercept + sum_i weights[i] * x_i).
    rung 2: for each feature f, z = (x_f - params[f].mean) / params[f].sd, g_f = sum_h a_h max(0, u_h z + c_h);
            p_site = sigmoid(intercept + sum_f g_f). fuse applies rungs 0 and 1 only (docs/learning.md L4).
    rung 0: no weights; the statistics alone (1 - p_comb).
    The neural rung's parameters are in the JSON; no site_model.pt, as torch is not a dependency.
    """
    cfg, sha = load(io.CONFIG_PATH)
    p, k, features = _params(cfg), int(cfg["learn"]["alert_budget"]), _features(cfg)
    train = [_site_weeks(cfg, r, s) for r in regimes for s in seeds]
    held, skipped = [], []
    for r in [r for r in cfg["learn"]["regimes"]["held_out"] if r not in regimes]:
        try:
            held += [_site_weeks(cfg, r, s) for s in seeds]
        except NotImplementedError:
            skipped.append(r)
    model = _ladder(train, held, features, p, k, seed=seeds[0] if seeds else 0)
    model["metrics"].update(
        held_out_regimes=sorted({rows["regime"].iloc[0] for rows, _ in held}),
        held_out_skipped=skipped,
    )
    model.update(config_hash=sha, seeds=list(seeds), regimes=list(regimes))
    model = _plain(model)
    path = model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, indent=1, sort_keys=True))
    return model
