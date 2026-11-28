"""Detection probability p_boat: logistic regression on candidate features, trained on injections."""

import numpy as np
import pandas as pd
import statsmodels.api as sm

from core.split import Split

FEATURES = ["peak_ratio_vv_db", "peak_ratio_vh_db", "pol_agree", "n_px", "wind_ms", "ghost"]


def features(cands: pd.DataFrame, exposure: pd.DataFrame) -> pd.DataFrame:
    """Feature matrix; wind_ms joined from coverage/exposure on (cell_id, pass_id). Index kept."""
    wind = exposure.drop_duplicates(["cell_id", "pass_id"]).set_index(["cell_id", "pass_id"])[
        "wind_ms"
    ]
    keys = pd.MultiIndex.from_frame(cands[["cell_id", "pass_id"]])
    X = cands.assign(wind_ms=wind.reindex(keys).to_numpy())
    return X[FEATURES].astype(float)


def fit_pboat(injection_cands: pd.DataFrame, split: Split):
    """statsmodels Logit of is_boat on FEATURES, fitted only on rows before the split's cut-off.

    injection_cands: P1's injection-run candidates with FEATURES, time_utc and is_boat
    (positives at injected boats, negatives > 500 m from any injection or AIS ship).
    """
    train = split.train(injection_cands.assign(date=injection_cands["time_utc"].dt.date))
    return sm.Logit(
        train["is_boat"].astype(float), sm.add_constant(train[FEATURES].astype(float))
    ).fit(disp=0)


def predict_pboat(model, X: pd.DataFrame) -> np.ndarray:
    return np.asarray(model.predict(sm.add_constant(X[FEATURES].astype(float), has_constant="add")))
