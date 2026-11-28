import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from core.split import Split
from sim.simulate import _make_weather, _p_det
from validate.detect_prob import _anchor_check, _fit, _mean_p, _recall_by_length

CFG = load(io.CONFIG_PATH)[0]
START = date.fromisoformat(CFG["sim"]["start_date"])


def _injected(seed: int, n: int) -> pd.DataFrame:
    """n boats on the simulator's calm days, detected with the simulator's own p_det (the injected truth)."""
    rng = np.random.default_rng(seed)
    w = _make_weather(CFG, CFG["sim"]["days"], seed)
    calm = np.flatnonzero(~w["rough"].to_numpy())
    day = rng.choice(calm, n)
    lo, hi = CFG["sim"]["small_boat_length_m"]
    length = rng.uniform(float(lo), float(hi), n)
    wind = w["wind_ms"].to_numpy()[day]
    return pd.DataFrame(
        {
            "date": [START + timedelta(days=int(d)) for d in day],
            "length_m": length,
            "wind_ms": wind,
            "hit": rng.random(n) < _p_det(CFG, length, wind),
        }
    )


ALL = Split(START + timedelta(days=CFG["sim"]["days"]))  # every simulated day is before the cutoff


@pytest.mark.slow
def test_detect_prob_fit_covers_truth():
    s = CFG["sim"]
    truth = {"const": s["det_a"], "length_m": s["det_b"], "wind_ms": -s["det_c"]}
    reps = 200
    inside = {k: 0 for k in truth}
    for r in range(reps):
        fit = _fit(_injected(r, 2000), ALL, ("length_m", "wind_ms"))
        for k, b in truth.items():
            inside[k] += fit["coef"][k]["lo"] <= b <= fit["coef"][k]["hi"]
    for k in truth:  # 95% +- 3 binomial standard deviations over 200 replicates
        assert 0.90 <= inside[k] / reps <= 0.995, (k, inside[k] / reps)


def test_fit_uses_only_rows_before_the_cutoff_and_drops_missing_terms():
    boats = _injected(0, 1500)
    cut = Split(START + timedelta(days=60))
    fit = _fit(boats, cut, ("log_length_m", "wind_ms", "incidence_deg"))
    assert fit["n"] == len(cut.train(boats)) < len(boats)
    assert set(fit["coef"]) == {"const", "log_length_m", "wind_ms"}
    assert "incidence_deg" in fit["dropped"]
    unknown = boats.assign(wind_ms=np.where(np.arange(len(boats)) % 2, np.nan, boats["wind_ms"]))
    assert (
        _fit(unknown, ALL, ("length_m", "wind_ms"))["n"] == len(boats) // 2
    )  # NaN wind is left out, never 0


def test_recall_by_length_has_wilson_intervals_and_null_for_empty_bins():
    boats = pd.DataFrame(
        {"length_m": [7.0] * 10 + [9.0] * 4, "hit": [True] * 5 + [False] * 5 + [True] * 4}
    )
    rows = _recall_by_length(boats, (0, 8, 12, 15)).to_dict("records")
    assert rows[0]["n"] == 10 and rows[0]["recall"] == 0.5
    assert abs(rows[0]["lo"] - 0.2366) < 1e-3 and abs(rows[0]["hi"] - 0.7634) < 1e-3
    assert rows[1]["recall"] == 1.0
    assert rows[2]["n"] == 0 and np.isnan(rows[2]["recall"])


def _big(recall: float, n: int = 400) -> pd.DataFrame:
    return pd.DataFrame({"length_m": np.linspace(15, 19.9, n), "hit": np.arange(n) < recall * n})


def test_injection_realism_anchor():
    anchor = CFG["detect_prob"]["realism_anchor"]
    bright = _big(0.95)
    before = bright.copy()
    with pytest.warns(UserWarning, match="too bright"):
        out = _anchor_check(bright, anchor)
    assert out["status"] == "far" and abs(out["recall"] - 0.95) < 1e-9
    pd.testing.assert_frame_equal(
        bright, before
    )  # never tunes: the data and the config are untouched
    assert CFG["detect_prob"]["realism_anchor"] == anchor
    with pytest.warns(UserWarning, match="too faint"):
        assert _anchor_check(_big(0.3), anchor)["status"] == "far"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _anchor_check(_big(0.6), anchor)["status"] == "near"
    with pytest.warns(UserWarning, match="cannot be checked"):
        assert _anchor_check(_big(0.6).assign(length_m=10.0), anchor)["status"] == "no_data"


def test_mean_p_is_null_without_a_length_mix_and_averages_with_one():
    fit = _fit(_injected(1, 1500), ALL, ("length_m", "wind_ms"))
    assert np.isnan(_mean_p(fit, 3.0, (6, 10, 15), None))
    lo = _mean_p(fit, 3.0, (6, 10, 15), (1.0, 0.0))
    hi = _mean_p(fit, 3.0, (6, 10, 15), (0.0, 1.0))
    mid = _mean_p(fit, 3.0, (6, 10, 15), (0.5, 0.5))
    assert lo < mid < hi and abs(mid - (lo + hi) / 2) < 1e-12
