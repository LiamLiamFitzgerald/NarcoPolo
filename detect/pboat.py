"""Detection probability p_boat from candidate features."""

import numpy as np
import pandas as pd


def features(cands, exposure) -> pd.DataFrame:  # stub, issue #6
    return pd.DataFrame(index=cands.index)


def fit_pboat(injection_cands, split):  # stub, issue #6
    return None


def predict_pboat(model, X) -> np.ndarray:  # stub, issue #6
    return np.zeros(len(X))
