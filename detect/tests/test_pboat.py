from datetime import UTC, datetime

import numpy as np
import pandas as pd
import statsmodels.api as sm

from core.split import Split
from detect.pboat import FEATURES, features, fit_pboat, predict_pboat

BETA = {"const": -6.0, "peak_ratio_vv_db": 0.5, "peak_ratio_vh_db": 0.2, "pol_agree": 1.0, "n_px": 0.1,
        "wind_ms": -0.2, "ghost": -3.0}  # fmt: skip
CUT = datetime(2026, 10, 1, tzinfo=UTC)


def _injections(n, seed, flip_after_cut=False):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "peak_ratio_vv_db": rng.uniform(7, 20, n), "peak_ratio_vh_db": rng.uniform(5, 18, n),
        "pol_agree": rng.random(n) < 0.5, "n_px": rng.integers(1, 30, n), "wind_ms": rng.uniform(0, 8, n),
        "ghost": rng.random(n) < 0.1,
        "time_utc": CUT + pd.to_timedelta(rng.uniform(-60, 30, n), unit="D"),
    })  # fmt: skip
    df["date"] = df["time_utc"].dt.date  # core.Split splits on the date
    eta = BETA["const"] + sum(BETA[f] * df[f].astype(float) for f in FEATURES)
    df["true_p"] = 1 / (1 + np.exp(-eta))
    df["label"] = rng.random(n) < df["true_p"]
    if flip_after_cut:
        df.loc[df["time_utc"] >= CUT, "label"] = ~df["label"]
    return df


def test_fit_recovers_known_coefficients_and_is_calibrated_out_of_sample():
    df = _injections(20_000, 0)
    split = Split(CUT.date(), test_days=23)
    m = fit_pboat(df, split)
    for k, b in BETA.items():
        assert abs(m.logit.params[k] - b) < 4 * m.logit.bse[k], k
    test = split.test(df)
    p = predict_pboat(m, test)
    rel = (
        pd.DataFrame({"p": p, "y": test["label"].to_numpy()})
        .assign(bin=pd.cut(p, np.linspace(0, 1, 11).tolist()))
        .groupby("bin", observed=True)
        .agg(["mean", "size"])
    )
    big = rel[("p", "size")] >= 100
    assert (abs(rel[("p", "mean")] - rel[("y", "mean")])[big] < 0.05).all()
    assert np.mean((p - test["label"]) ** 2) < np.mean((test["label"].mean() - test["label"]) ** 2)


def test_fit_never_sees_data_after_the_cutoff():
    a = fit_pboat(_injections(5000, 1), Split(CUT.date(), test_days=23)).logit.params
    b = fit_pboat(
        _injections(5000, 1, flip_after_cut=True), Split(CUT.date(), test_days=23)
    ).logit.params
    assert np.allclose(a, b)


def test_features_join_wind_on_cell_and_pass():
    cands = pd.DataFrame({"cell_id": ["a", "b", "a"], "pass_id": ["p1", "p1", "p2"], "peak_ratio_vv_db": 10.0,
                          "peak_ratio_vh_db": 8.0, "pol_agree": True, "n_px": 3, "ghost": False}, index=[5, 6, 7])  # fmt: skip
    exp = pd.DataFrame(
        {"cell_id": ["a", "b", "a"], "pass_id": ["p1", "p1", "p2"], "wind_ms": [1.0, 2.0, 3.0]}
    )
    X = features(cands, exp)
    assert (
        list(X.index) == [5, 6, 7]
        and list(X["wind_ms"]) == [1.0, 2.0, 3.0]
        and list(X.columns) == FEATURES
    )


def _reliability_gap(p, y):
    rel = pd.DataFrame({"p": p, "y": y}).assign(bin=pd.cut(p, np.linspace(0, 1, 11).tolist()))
    g = rel.groupby("bin", observed=True).agg(["mean", "size"])
    big = g[("p", "size")] >= 100
    return float(abs(g[("p", "mean")] - g[("y", "mean")])[big].max())


def test_isotonic_recalibration_fixes_a_miscalibrated_logit():
    """True p = 0.3 sigmoid(eta): a ceiling the Logit cannot fit, monotone in its output, so the isotonic map can."""
    df = _injections(40_000, 2)
    df["label"] = np.random.default_rng(3).random(len(df)) < 0.3 * df["true_p"]
    split = Split(CUT.date(), test_days=23)
    m = fit_pboat(df, split)
    test = split.test(df)
    raw = np.asarray(
        m.logit.predict(sm.add_constant(test[FEATURES].astype(float), has_constant="add"))
    )
    cal = predict_pboat(m, test)
    y = test["label"].to_numpy(float)
    assert _reliability_gap(cal, y) < 0.05 < _reliability_gap(raw, y)
    assert np.mean((cal - y) ** 2) < np.mean((raw - y) ** 2)


def test_one_training_date_keeps_the_logit_output():
    df = _injections(3000, 4).assign(date=(CUT - pd.Timedelta(days=3)).date())
    m = fit_pboat(df, Split(CUT.date()))
    assert np.allclose(
        predict_pboat(m, df), m.logit.predict(sm.add_constant(df[FEATURES].astype(float)))
    )
