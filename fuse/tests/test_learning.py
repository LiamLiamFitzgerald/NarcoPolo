"""L3 + L4 apply (docs/learning.md): CCT, calibration, merged agreement, site_value and its rung-0 fallback."""

import json

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from fuse import combine, learn


def _equal(cols) -> pd.Series:
    return pd.Series(1 / len(cols), index=list(cols))


@pytest.mark.parametrize("p", [1e-6, 0.01, 0.2, 0.5, 0.9])
def test_cct_of_identical_p_is_p(p):
    pv = pd.DataFrame({a: [p] for a in "abcd"})
    assert combine.cct(pv, _equal(pv.columns)).iloc[0] == pytest.approx(p, rel=1e-9)


def test_cct_is_monotone_in_each_p():
    rng = np.random.default_rng(1)
    pv = pd.DataFrame(rng.uniform(size=(200, 3)), columns=list("abc"))
    w = _equal(pv.columns)
    base = combine.cct(pv, w)
    for a in pv.columns:
        lower = pv.assign(**{a: pv[a] * rng.uniform(size=len(pv))})
        assert (combine.cct(lower, w) <= base + 1e-12).all()


def test_cct_in_unit_interval_and_skips_missing_agents():
    pv = pd.DataFrame({"a": [0.0, 1.0, 0.3], "b": [np.nan, 1.0, np.nan]})
    p = combine.cct(pv, _equal(pv.columns))
    assert p.between(0, 1).all()
    assert p.iloc[2] == pytest.approx(0.3)  # b missing: a alone


def test_merged_group_counts_once():
    """Three agents in one merged group carry the weight of one: no double counting."""
    w = combine.weights(["oe", "midp", "cusum", "link"], [["oe", "midp", "cusum"], ["link"]])
    assert w["link"] == pytest.approx(0.5) and w[["oe", "midp", "cusum"]].sum() == pytest.approx(
        0.5
    )


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_calibration_on_uniform_nulls_hits_target(seed):
    rng = np.random.default_rng(seed)
    n_weeks, n_sites, target = 52, 40, 1.0
    idx = pd.MultiIndex.from_product([range(n_weeks), range(n_sites)])
    t = combine.calibrate(pd.Series(rng.uniform(size=len(idx)), index=idx), target)
    assert t == pytest.approx(target / n_sites, rel=0.35)  # uniform: alerts/week = n_sites * t
    fresh = rng.uniform(size=(n_weeks, n_sites))
    assert (fresh <= t).sum() / n_weeks == pytest.approx(target, abs=0.5)


def test_calibration_allows_no_alert_when_target_is_zero():
    assert combine.calibrate(pd.Series([0.001, 0.5], index=[0, 1]), 0.0) == 0.0


def test_agreement_counts_groups_that_flag():
    pv = pd.DataFrame({"a": [1e-6] + [0.5] * 9, "b": [1e-6] + [0.5] * 9, "c": [0.5] * 10})
    n = combine.agreement_merged(pv, [["a", "b"], ["c"]], q=0.1)
    assert n.tolist() == [1] + [0] * 9


def test_flags_respects_calibrated_threshold():
    p = pd.Series([1e-6, 1e-4, 0.5])
    assert combine.flags(p, 0.1).tolist() == [True, True, False]
    assert combine.flags(p, 0.1, threshold=1e-5).tolist() == [True, False, False]


def _model(**kw):
    return {"rung": 1, "features": ["link", "oe"], "weights": [1.5, 0.5], "intercept": -2.0} | kw


def _sites(n=30, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "p_comb": rng.uniform(size=n),
            "link": rng.exponential(size=n),
            "oe": rng.exponential(size=n),
        }
    )


def test_rung1_is_monotone_in_every_feature():
    s = _sites()
    p, rung = learn._site_value(s, _model())
    assert rung == 1 and p.between(0, 1).all()
    for f in ("link", "oe"):
        assert (learn._site_value(s.assign(**{f: s[f] + 1}), _model())[0] >= p).all()


@pytest.mark.parametrize(
    "bad",
    [
        None,
        _model(weights=[1.0, -0.1]),
        _model(features=["link", "gone"]),
        _model(rung=2),
        {"rung": 1},
    ],
)
def test_unusable_model_falls_back_to_rung0(bad):
    s = _sites()
    p = learn.site_value(s, bad)
    assert p.attrs["rung"] == 0 and p.between(0, 1).all()
    assert p.idxmax() == s["p_comb"].idxmin()  # rung 0 ranks by 1 - p_comb


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path))
    monkeypatch.setenv("NARCO_REPORTS", str(tmp_path / "reports"))
    return tmp_path


def test_missing_or_stale_model_file_gives_none(data_root):
    assert learn.load_model() is None
    learn.model_path().parent.mkdir(parents=True)
    learn.model_path().write_text(json.dumps(_model(config_hash="stale")))
    assert learn.load_model() is None
    learn.model_path().write_text("{not json")
    assert learn.load_model() is None
    learn.model_path().write_text(json.dumps(_model(config_hash=load(io.CONFIG_PATH)[1])))
    assert learn.load_model() is not None


def test_groups_follow_signals_json_once_written(data_root):
    assert combine.groups() == [[a] for a in load(io.CONFIG_PATH)[0]["learn"]["agents"]]
    (data_root / "reports").mkdir()
    (data_root / "reports" / "signals.json").write_text(
        json.dumps({"merged": [["oe", "midp"], ["link"]]})
    )
    assert combine.groups() == [["oe", "midp"], ["link"]]


def _stub_sites(n=12, seed=3):
    """Stand-in for fuse.sites() output until issue 24 lands (sites() is still a stub returning no rows)."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {"site_id": [f"s{i}" for i in range(n)], "p_perm": rng.uniform(size=n) ** 2}
    )


def test_learning_columns_on_every_row_rung0(data_root):
    out = learn._add_learning_columns(_stub_sites(), 0.1)
    for c in ("p_comb", "comb_flag", "agreement_merged", "p_site", "model_rung"):
        assert out[c].notna().all()
    assert (out["model_rung"] == 0).all() and out["p_site"].between(0, 1).all()
    assert out["p_comb"].to_numpy() == pytest.approx(
        out["p_perm"].to_numpy()
    )  # link is the only agent yet


def test_learning_columns_use_a_fresh_rung1_model(data_root):
    learn.model_path().parent.mkdir(parents=True)
    model = {"rung": 1, "features": ["link"], "weights": [1.0], "intercept": 0.0}
    learn.model_path().write_text(json.dumps(model | {"config_hash": load(io.CONFIG_PATH)[1]}))
    s = _stub_sites()
    out = learn._add_learning_columns(s, 0.1)
    assert (out["model_rung"] == 1).all()
    assert out["p_site"].idxmax() == s["p_perm"].idxmin()  # monotone in -log10 p_perm


def test_empty_sites_still_get_the_columns(data_root):
    out = learn._add_learning_columns(_stub_sites(0), 0.1)
    assert {"p_comb", "comb_flag", "agreement_merged", "p_site", "model_rung"} <= set(out.columns)


def test_merged_list_without_link_gives_p_comb_one_not_a_crash(data_root):
    (data_root / "reports").mkdir()
    (data_root / "reports" / "signals.json").write_text(json.dumps({"merged": [["oe"]]}))
    out = learn._add_learning_columns(_stub_sites(), 0.1)
    assert (out["p_comb"] == 1.0).all() and not out["comb_flag"].any()


def test_null_pvalue_is_the_empirical_tail_share():
    null = np.arange(1, 100)  # 99 samples
    p = combine.null_pvalue(pd.Series([0.0, 50.0, 1000.0, np.nan]), null)
    assert p.iloc[0] == pytest.approx(1.0)  # below every sample
    assert p.iloc[1] == pytest.approx((1 + 50) / 100)  # 50..99 are >= 50
    assert p.iloc[2] == pytest.approx(1 / 100)  # rarer than all, never 0
    assert np.isnan(p.iloc[3])


@pytest.mark.parametrize("seed", [0, 1])
def test_null_pvalue_is_uniform_under_the_null(seed):
    rng = np.random.default_rng(seed)
    p = combine.null_pvalue(pd.Series(rng.normal(size=4000)), rng.normal(size=5000))
    assert (p <= 0.05).mean() == pytest.approx(0.05, abs=0.015)


def test_scores_with_null_samples_join_the_combination(data_root):
    (data_root / "reports").mkdir()
    null = sorted(np.random.default_rng(0).normal(size=999).tolist())
    (data_root / "reports" / "signals.json").write_text(
        json.dumps({"merged": [["oe"], ["link"]], "null": {"oe": null}})
    )
    s = _stub_sites().assign(score_oe=np.linspace(-1, 5, 12))
    pv = learn._agent_pvalues(s, ["oe", "link"])
    assert list(pv.columns) == ["link", "oe"] and pv["oe"].is_monotonic_decreasing
    out = learn._add_learning_columns(s, 0.1)
    assert not np.allclose(out["p_comb"], out["p_perm"])  # oe now counts


def test_score_without_null_samples_is_left_out(data_root):
    s = _stub_sites().assign(score_gi=1.0)
    assert list(learn._agent_pvalues(s, ["gi", "link"]).columns) == ["link"]
