"""Detection probability p_boat: logistic regression on candidate features, trained on injections,
then an isotonic recalibration of its output (#209)."""

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import isotonic_regression

from core.split import Split

FEATURES = ["peak_ratio_vv_db", "peak_ratio_vh_db", "pol_agree", "n_px", "wind_ms", "ghost"]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PBoat:
    logit: Any  # statsmodels Logit result
    knots: tuple[np.ndarray, np.ndarray]  # isotonic map: Logit output -> calibrated p (np.interp)


def features(cands: pd.DataFrame, exposure: pd.DataFrame) -> pd.DataFrame:
    """Feature matrix; wind_ms joined from coverage/exposure on (cell_id, pass_id). Index kept."""
    wind = exposure.drop_duplicates(["cell_id", "pass_id"]).set_index(["cell_id", "pass_id"])[
        "wind_ms"
    ]
    keys = pd.MultiIndex.from_frame(cands[["cell_id", "pass_id"]])
    X = cands.assign(wind_ms=wind.reindex(keys).to_numpy())
    return X[FEATURES].astype(float)


def _logit_p(logit: Any, X: pd.DataFrame) -> np.ndarray:
    return np.asarray(logit.predict(sm.add_constant(X[FEATURES].astype(float), has_constant="add")))


def fit_pboat(injection_cands: pd.DataFrame, split: Split) -> _PBoat:
    """Logit of label on FEATURES, then isotonic recalibration, both on rows dated before the split's cut-off.

    injection_cands: validate/pboat_training rows with FEATURES (wind_ms joined), date and label.
    The training dates are halved at their median: the Logit fits the earlier half and the isotonic map the
    later half, so the map sees predictions out of sample. With a single training date there is no later
    half and the map is the identity.
    """
    train = split.train(injection_cands).dropna(subset=FEATURES)
    if train.empty:
        raise ValueError(f"no p_boat training rows before {split.cutoff}")
    d = pd.to_datetime(train["date"])
    late = d > d.median()
    early = train[~late]
    logit = sm.Logit(
        early["label"].astype(float), sm.add_constant(early[FEATURES].astype(float))
    ).fit(disp=0)
    if not late.any():
        log.warning("p_boat: one training date, no isotonic recalibration")
        return _PBoat(logit, (np.array([0.0, 1.0]), np.array([0.0, 1.0])))
    p = _logit_p(logit, train[late])
    o = np.argsort(p)
    fit = isotonic_regression(train[late]["label"].to_numpy(float)[o]).x
    return _PBoat(logit, (p[o], fit))


def predict_pboat(model: _PBoat, X: pd.DataFrame) -> np.ndarray:
    return np.interp(_logit_p(model.logit, X), *model.knots)
