"""Small-boat detection-probability curve (#349), fitted on injected boats with known truth.

The boats are the ones validate.recall_curve already scores (true boats under 24 m in a pass footprint, hit = a
non-ghost detection of that pass within 300 m), on calm passes only: rough passes look for no small boats
(principle 5), so they say nothing about p_detect. Each boat takes its cell-pass wind from coverage/exposure.

logit p_detect = b0 + sum of the `detect_prob.form` terms, a statsmodels Binomial GLM on the training rows of a
core.Split. A term missing from the data is dropped and named in the report: the simulator has no per-boat
incidence angle (its scenes carry one fixed min-max range), so incidence_deg is dropped on the simulator.
Fitted coefficients go to reports/detect_prob.json, never into config.

Paolo et al. 2024's 60% recall at 15-20 m is a warning check only: it never changes a fit or a threshold.
"""

import json
import os
import warnings
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from core import io
from core.config import load
from core.split import Split, folds
from validate.checks import _boat_hits, _clean, wilson

_TERMS = {
    "log_length_m": lambda b: np.log(b["length_m"]),
    "length_m": lambda b: b["length_m"],
    "wind_ms": lambda b: b["wind_ms"],
    "incidence_deg": lambda b: b["incidence_deg"],
}


def _boats(detections: pd.DataFrame, truth: pd.DataFrame, exposure: pd.DataFrame) -> pd.DataFrame:
    """Injected boats on calm passes: date, length_m, wind_ms (NaN where unknown), hit."""
    boats = _boat_hits(detections, truth)
    cells = exposure.set_index(["cell_id", "pass_id"])[["wind_ms", "calm"]]
    boats = boats.join(cells, on=["cell_id", "pass_id"])  # no exposure row: calm unknown, left out
    boats = boats[boats["calm"].eq(True)]
    return boats.assign(date=pd.to_datetime(boats["time_utc"], utc=True).dt.date)


def _fit(boats: pd.DataFrame, split: Split, form: Sequence[str]) -> dict[str, Any]:
    """Binomial GLM of hit on the form's terms, training rows only; 95% Wald intervals per coefficient."""
    train = split.train(boats)
    split.assert_train(train)
    terms = [t for t in form if t.removeprefix("log_") in train]
    dropped = [t for t in form if t not in terms]
    X = pd.DataFrame({t: _TERMS[t](train) for t in terms}, index=train.index)
    keep = X.notna().all(axis=1)  # unknown wind or angle: left out, never 0
    X = pd.DataFrame(sm.add_constant(X[keep], has_constant="add"))
    res = sm.GLM(train.loc[keep, "hit"].astype(float), X, family=sm.families.Binomial()).fit()
    ci = res.conf_int(0.05)
    coef = {
        k: {
            "b": float(res.params[k]),
            "se": float(res.bse[k]),
            "lo": float(ci.loc[k, 0]),
            "hi": float(ci.loc[k, 1]),
        }
        for k in X.columns
    }
    return {
        "form": list(form),
        "dropped": dropped,
        "n": int(keep.sum()),
        "cutoff": str(split.cutoff),
        "coef": coef,
    }


def _p(fit: Mapping[str, Any], frame: pd.DataFrame) -> np.ndarray:
    c = fit["coef"]
    eta = c["const"]["b"] + sum(
        c[t]["b"] * np.asarray(_TERMS[t](frame), float) for t in c if t != "const"
    )
    return 1 / (1 + np.exp(-eta))


def _mean_p(
    fit: Mapping[str, Any], wind_ms: float, edges: Sequence[float], weights: Sequence[float] | None
) -> float:
    """p̄_detect at one pass's wind: the length-mix-weighted mean of p over each bin; NaN without a mix."""
    if weights is None:
        return float("nan")
    per_bin = [
        _p(fit, pd.DataFrame({"length_m": np.linspace(lo, hi, 21), "wind_ms": wind_ms})).mean()
        for lo, hi in pairwise(edges)
    ]
    return float(np.dot(weights, per_bin) / np.sum(weights))


def _recall_by_length(boats: pd.DataFrame, edges: Sequence[float]) -> pd.DataFrame:
    rows = []
    for lo, hi in pairwise(edges):
        g = boats[(boats["length_m"] >= lo) & (boats["length_m"] < hi)]
        k, n = int(g["hit"].sum()), len(g)
        lo_, hi_ = wilson(k, n)
        rows.append({"length_lo": lo, "length_hi": hi, "n": n, "detected": k,
                     "recall": k / n if n else np.nan, "lo": lo_, "hi": hi_})  # fmt: skip
    return pd.DataFrame(rows)


def _anchor_check(boats: pd.DataFrame, anchor: Mapping[str, Any]) -> dict[str, Any]:
    """Warn when the anchor recall lies outside the Wilson 95% interval of injected recall in its length band."""
    lo_m, hi_m = anchor["length_m"]
    g = boats[(boats["length_m"] >= lo_m) & (boats["length_m"] < hi_m)]
    k, n = int(g["hit"].sum()), len(g)
    out: dict[str, Any] = {"anchor": float(anchor["recall"]), "length_m": [lo_m, hi_m], "n": n}
    if n == 0:
        warnings.warn(
            f"realism anchor cannot be checked: no injected boats at {lo_m}-{hi_m} m", stacklevel=2
        )
        return out | {"status": "no_data", "recall": None, "lo": None, "hi": None}
    lo, hi = wilson(k, n)
    out |= {
        "recall": k / n,
        "lo": lo,
        "hi": hi,
        "status": "near" if lo <= anchor["recall"] <= hi else "far",
    }
    if out["status"] == "far":
        side = "too bright" if lo > anchor["recall"] else "too faint"
        warnings.warn(
            f"injected recall at {lo_m}-{hi_m} m is {k / n:.2f} against the published {anchor['recall']}: "
            f"injections are probably {side}. Worth checking; this never tunes anything",
            stacklevel=2,
        )
    return out


def _report() -> Path:
    """reports/detect_prob.json from the simulator truth, detections and exposure."""
    cfg, _ = load(io.CONFIG_PATH)
    dp, s = cfg["detect_prob"], cfg["split"]
    boats = _boats(
        io.read_stage("detect/detections"),
        pd.read_parquet(io.truth_path()),
        io.read_stage("coverage/exposure"),
    )
    cutoff = folds(io.read_snapshot()["T"], s["n_folds_small"])[
        -1
    ].cutoff  # as validate.train: before every test week
    split = Split(cutoff, s["embargo_days"], s["test_days"])
    fit = _fit(boats, split, dp["form"])
    out = fit | {
        "recall_by_length": _recall_by_length(split.train(boats), dp["length_bins_m"]),
        "realism_anchor": _anchor_check(split.train(boats), dp["realism_anchor"]),
        "mean_p_detect": {  # null for every pass until #365 gives a length mix
            pid: _mean_p(fit, w, dp["length_bins_m"], dp["length_weights"])
            for pid, w in split.train(boats).groupby("pass_id")["wind_ms"].first().items()
        },
    }
    path = Path(os.environ.get("NARCO_REPORTS", io.ROOT / "reports")) / "detect_prob.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(out), indent=1, allow_nan=False))
    return path
