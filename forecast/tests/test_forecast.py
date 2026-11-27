import numpy as np
import pandas as pd
import pytest

from core.split import Split, folds
from forecast import (
    EXPECTED_COLUMNS,
    backtest,
    choose_baseline,
    design_matrix,
    empirical_bayes,
    evaluation_split,
    ewma,
    expected_rows,
    forecast_window,
    glm_mu,
    nb_interval,
    poisson_deviance,
)
from forecast.tests import fake_sim

TYPES = ["dark_small", "slowdown"]
DELTA, MIN_SE, LEVEL = 0.97, 3.0, 0.9  # spec defaults; real runs read them from config
SPLIT = Split((fake_sim.START + pd.Timedelta(days=90)).date(), embargo_days=0, test_days=30)


def _setup(event_type, fine_frame=None):
    fine, coarse, cells = fake_sim.observed(event_type)
    f2 = fine.frame if fine_frame is None else fine_frame
    f10 = coarse.frame
    dates = pd.DatetimeIndex(f2.date.unique())
    X2 = design_matrix(cells[cells.level == 2000], dates, event_type)
    X10 = design_matrix(cells[cells.level == 10000], dates, event_type)
    return f2, f10, X2, X10, cells


def _ewma(f2, f10, split=SPLIT):
    return ewma(split, split.train(f2), split.train(f10), split.test(f2), DELTA, MIN_SE)


def _glm(f2, f10, X2, X10, split=SPLIT):
    return glm_mu(split, split.train(f10), X10, split.test(f2), X2)


def _recovery(test, mu, cells):
    """sum(mu) / sum(true rate x E) per group of cells; 1.0 is perfect."""
    fine = cells[cells.level == 2000].set_index("cell_id")
    t = test.assign(mu=mu, true=test.cell_id.map(fake_sim.planted_rate(fine)) * test.exposure)
    t = t[t.exposure > 0]
    lane = t.cell_id.map(fine.lane) == 1
    inshore = t.cell_id.map(fine.inshore_frac)
    groups = {
        "lane": lane,
        "inshore": inshore > 0.7,
        "offshore": (inshore < 0.2) & ~lane,
    }
    return {g: t[m].mu.sum() / t[m].true.sum() for g, m in groups.items()}


@pytest.mark.parametrize("event_type", TYPES)
def test_ewma_recovers_planted_rates_within_20_percent(event_type):
    f2, f10, _, _, cells = _setup(event_type)
    ratios = _recovery(SPLIT.test(f2), _ewma(f2, f10), cells)
    assert all(0.8 <= r <= 1.2 for r in ratios.values()), ratios


@pytest.mark.xfail(
    strict=True,
    reason="spec gap: fitting on 10 km and applying beta to 2 km over-predicts lane cells ~35% "
    "(a 2-row lane band inside a 10 km cell); needs a P1/P3 decision",
)
@pytest.mark.parametrize("event_type", TYPES)
def test_glm_recovers_planted_rates_within_20_percent(event_type):
    f2, f10, X2, X10, cells = _setup(event_type)
    mu, phi = _glm(f2, f10, X2, X10)
    ratios = _recovery(SPLIT.test(f2), mu, cells)
    assert all(0.8 <= r <= 1.2 for r in ratios.values()), ratios
    assert phi == pytest.approx(1.0, abs=0.3)  # the simulator is Poisson


def test_drop_site_days_are_not_absorbed_into_the_baseline():
    f2, f10, X2, X10, _ = _setup("slowdown")
    site = "2000_10_25"
    drop_days = f2.date.isin(pd.date_range(fake_sim.START, periods=12, freq="10D"))
    f2 = f2.copy()
    f2.loc[(f2.cell_id == site) & drop_days, "count"] += 3
    test = SPLIT.test(f2)
    on_site = ((test.cell_id == site) & test.date.isin(f2.date[drop_days])).to_numpy()
    assert on_site.any()
    assert (_ewma(f2, f10)[on_site] < 3).all()
    assert (_glm(f2, f10, X2, X10)[0][on_site] < 3).all()


@pytest.mark.parametrize("event_type", TYPES)
def test_future_row_in_training_data_makes_the_fit_raise(event_type):
    f2, f10, X2, X10, _ = _setup(event_type)
    leak = SPLIT.test(f2).head(1)
    with pytest.raises(ValueError, match="look-ahead"):
        ewma(
            SPLIT,
            pd.concat([SPLIT.train(f2), leak]),
            SPLIT.train(f10),
            SPLIT.test(f2),
            DELTA,
            MIN_SE,
        )
    leak10 = SPLIT.test(f10).head(1)
    with pytest.raises(ValueError, match="look-ahead"):
        glm_mu(SPLIT, pd.concat([SPLIT.train(f10), leak10]), X10, SPLIT.test(f2), X2)


def test_unobserved_rows_get_mu_zero_and_no_surprise():
    f2, f10, X2, X10, _ = _setup("dark_small")
    test = SPLIT.test(f2)
    unobserved = (test.exposure == 0).to_numpy()
    assert unobserved.any()
    for mu in (_ewma(f2, f10), _glm(f2, f10, X2, X10)[0]):
        assert (mu[unobserved] == 0).all()
        lo, hi = nb_interval(mu, 2.0, LEVEL)
        assert (lo[unobserved] == 0).all() and (hi[unobserved] == 0).all()


@pytest.mark.parametrize("event_type", TYPES)
def test_no_negative_or_missing_mu_or_interval_where_exposure_positive(event_type):
    f2, f10, X2, X10, _ = _setup(event_type)
    seen = (SPLIT.test(f2).exposure > 0).to_numpy()
    mu, phi = _glm(f2, f10, X2, X10)
    lo, hi = nb_interval(mu, phi, LEVEL)
    assert (mu[seen] >= 0).all() and mu[seen].notna().all()
    assert np.isfinite(lo[seen]).all() and np.isfinite(hi[seen]).all()


def test_interval_covers_about_ninety_percent():
    f2, f10, X2, X10, _ = _setup("slowdown")
    mu, phi = _glm(f2, f10, X2, X10)
    test = SPLIT.test(f2)
    lo, hi = nb_interval(mu, phi, LEVEL)
    coverage = ((test["count"] >= lo) & (test["count"] <= hi)).mean()
    assert 0.88 <= coverage <= 0.995, (
        coverage
    )  # discrete counts make central intervals conservative


def test_negative_binomial_interval_is_wider_when_overdispersed():
    mu = pd.Series([4.0])
    lo1, hi1 = nb_interval(mu, 1.0, LEVEL)
    lo3, hi3 = nb_interval(mu, 3.0, LEVEL)
    assert hi3[0] > hi1[0] and lo3[0] <= lo1[0]


def test_empirical_bayes_without_extra_variation_is_one():
    M = pd.Series([2.0, 3.0, 5.0])
    assert (empirical_bayes(M.copy(), M) == 1).all()


def test_empirical_bayes_pulls_thin_cells_towards_one():
    O = pd.Series([0.0, 30.0, 200.0])
    M = pd.Series([1.0, 10.0, 100.0])
    theta = empirical_bayes(O, M)
    raw = O / M
    assert (abs(theta - 1) <= abs(raw - 1)).all()


def test_poisson_deviance_is_zero_for_a_perfect_forecast_and_handles_soft_zeros():
    assert poisson_deviance(pd.Series([0.6, 2.0]), pd.Series([0.6, 2.0])) == pytest.approx(0)
    assert poisson_deviance(pd.Series([0.0]), pd.Series([0.5])) == pytest.approx(1.0)


@pytest.mark.xfail(
    strict=True,
    reason="spec gap: cells with no training events get rate 0 (EWMA and flat), so one event "
    "makes the deviance infinite and skill NaN or a fake 1.0; needs a P1 decision",
)
@pytest.mark.parametrize("event_type,k", [("dark_small", 6), ("slowdown", 12)])
def test_walk_forward_backtest_beats_flat_average(event_type, k):
    f2, f10, X2, X10, _ = _setup(event_type)
    T = f2.date.max()
    fs = folds(T.date(), k)
    skills = {
        "ewma": backtest(f2, fs, lambda s: _ewma(f2, f10, s)),
        "glm": backtest(f2, fs, lambda s: _glm(f2, f10, X2, X10, s)[0]),
    }
    for name, table in skills.items():
        print(event_type, name, table.skill.agg(["mean", "min", "max"]).round(4).to_dict())
    for table in skills.values():
        assert np.isfinite(table.skill).all() and (table.skill < 1).all()
    assert skills["glm"].skill.mean() > 0


def _frames(event_type, fine_frame=None):
    f2, f10, X2, X10, _ = _setup(event_type, fine_frame)
    return f2, f10, X2, X10


def _window(model, frames):
    T = frames[0].date.max()
    return forecast_window(model, T, frames, DELTA, MIN_SE, LEVEL)


def test_evaluation_window_runs_from_monday_three_weeks_back_to_T():
    for T in pd.date_range("2026-11-02", periods=7):  # Monday .. Sunday
        s = evaluation_split(T)
        days = pd.date_range(pd.Timestamp(s.cutoff), T)
        assert s.cutoff.weekday() == 0 and 22 <= len(days) <= 28
        assert len(s.test(pd.DataFrame({"date": days}))) == len(days)


@pytest.mark.parametrize("model", ["ewma", "glm"])
@pytest.mark.parametrize("event_type", TYPES)
def test_forecast_window_rows_match_the_expected_contract(model, event_type):
    frames = _frames(event_type)
    rows = _window(model, frames)
    window = evaluation_split(frames[0].date.max()).test(frames[0])
    assert list(rows.columns) == EXPECTED_COLUMNS
    assert len(rows) == len(window)
    assert (rows.fold == 0).all() and (rows.model == model).all()
    seen = window.exposure.to_numpy() > 0
    assert (rows.mu >= 0).all()
    assert rows.loc[seen, ["mu", "lo90", "hi90"]].notna().all().all()
    # integer bounds: for mu below ~0.05 the 90% interval is [0, 0], so mu may exceed hi90
    assert ((rows.lo90 >= 0) & (rows.lo90 <= rows.hi90) & (rows.lo90 <= rows.mu)).all()


@pytest.mark.parametrize("model", ["ewma", "glm"])
def test_days_being_scored_never_shape_their_own_baseline(model):
    frames = _frames("slowdown")
    f2 = frames[0].copy()
    window = evaluation_split(f2.date.max()).test(f2)
    f2.loc[window.index, "count"] += 50  # a wild window: must not move mu
    from aggregate import to_coarse
    from core.observed import Observed

    spiked = (f2, to_coarse(Observed(f2)).frame, frames[2], frames[3])
    pd.testing.assert_series_equal(_window(model, frames).mu, _window(model, spiked).mu)


def test_backtest_rows_carry_their_fold_number():
    frames = _frames("dark_small")
    fs = folds(frames[0].date.max().date(), 3)
    rows = pd.concat(
        [expected_rows("glm", s, k, frames, DELTA, MIN_SE, LEVEL) for k, s in enumerate(fs, 1)]
    )
    assert sorted(rows.fold.unique()) == [1, 2, 3]
    assert rows.groupby("fold").date.nunique().eq(7).all()


def test_choose_baseline_records_the_higher_mean_skill(tmp_path):
    decisions = tmp_path / "DECISIONS.md"
    skills = {
        "ewma": pd.DataFrame({"fold": [1, 2], "skill": [0.05, 0.10]}),
        "glm": pd.DataFrame({"fold": [1, 2], "skill": [0.20, 0.12]}),
    }
    assert choose_baseline("slowdown", skills, str(decisions), "2026-11-28 10:00") == "glm"
    line = decisions.read_text()
    assert "slowdown: glm" in line and "range 0.120 to 0.200" in line


def test_choose_baseline_refuses_a_broken_backtest(tmp_path):
    decisions = tmp_path / "DECISIONS.md"
    skills = {
        "ewma": pd.DataFrame({"fold": [1], "skill": [np.nan]}),
        "glm": pd.DataFrame({"fold": [1], "skill": [0.1]}),
    }
    with pytest.raises(ValueError, match="non-finite"):
        choose_baseline("dark_small", skills, str(decisions), "2026-11-28 10:00")
    assert not decisions.exists()


CFG = {
    "ewma_delta": DELTA,
    "ewma_min_se": MIN_SE,
    "interval": LEVEL,
    "split": {"n_folds_slowdown": 12, "n_folds_small": 6},
}


def _all_observed():
    parts, cells = [], None
    for et in TYPES:
        fine, coarse, cells = fake_sim.observed(et)
        parts += [fine.frame, coarse.frame]
    return pd.concat(parts, ignore_index=True), cells


def test_stage_run_writes_window_and_fold_rows_with_a_report(tmp_path):
    from forecast import forecast_all

    observed, cells = _all_observed()
    T = observed.date.max()
    forced = {"slowdown": "glm", "dark_small": "ewma"}
    expected, report = forecast_all(
        observed, cells, T, CFG, str(tmp_path / "D.md"), "2026-11-28 10:00", forced
    )
    assert list(expected.columns) == EXPECTED_COLUMNS
    folds_by_type = expected.groupby("event_type").fold.nunique()
    assert folds_by_type["slowdown"] == 13 and folds_by_type["dark_small"] == 7  # fold 0 + K
    assert set(expected.groupby("event_type").model.unique().map(tuple)) == {
        ("glm",),
        ("ewma",),
    }
    assert (expected.fold == 0).sum() == 2 * len(
        evaluation_split(T).test(
            observed[(observed.level == 2000) & (observed.event_type == "slowdown")]
        )
    )
    assert report.chosen.sum() == 2 and not (tmp_path / "D.md").exists()  # forced: nothing recorded
    assert (report.nb2_alpha < 0.1).all()  # the fake simulator is Poisson: NB2 agrees with phi ~ 1
    print(report.round(3).to_string())


def test_undefined_skill_falls_back_to_ewma_and_records_nothing(tmp_path):
    from forecast import forecast_all

    observed, cells = _all_observed()
    decisions = tmp_path / "D.md"
    expected, _ = forecast_all(observed, cells, observed.date.max(), CFG, str(decisions), "x")
    # dark_small skill is NaN on the fake simulator (#58): no comparison was made, nothing recorded
    assert (expected[expected.event_type == "dark_small"].model == "ewma").all()
    assert "dark_small" not in (decisions.read_text() if decisions.exists() else "")


@pytest.mark.xfail(
    strict=True,
    reason="#90: the simulator writes dark_small events on rough passes (exposure 0), "
    "which core.Observed rightly refuses",
)
def test_p1_simulator_runs_through_both_p5_stages(tmp_path, monkeypatch):
    """End to end on sim.simulate's files: aggregate.stage then forecast.stage, schemas checked."""
    from aggregate import stage as aggregate_stage
    from core.config import load
    from core.io import CONFIG_PATH, read_snapshot, read_stage
    from forecast import stage as forecast_stage
    from sim.simulate import simulate

    monkeypatch.setenv("NARCO_DATA", str(tmp_path))
    cfg, _ = load(CONFIG_PATH)
    simulate(cfg, cfg["seed"])
    # P5's keys until P1 adds them to config.yaml (#69); values from the spec
    p5 = {
        **cfg,
        "ewma_delta": DELTA,
        "ewma_min_se": MIN_SE,
        "interval": LEVEL,
        "ship_history_days": cfg["sim"]["days"],
        "radar_history_days": 90,
    }
    snap = read_snapshot()
    T = pd.Timestamp(snap["T"])
    aggregate_stage(T, pd.Timestamp(snap["gfw_presence"]), p5, "simulated")
    obs = read_stage("aggregate/observed")
    assert set(obs.level) == {2000, 10000} and set(obs.event_type) == set(TYPES)
    forecast_stage(T, p5, "simulated", str(tmp_path / "D.md"), "2026-11-28 10:00")
    live = read_stage("forecast/expected").query("fold == 0")
    assert set(live.event_type) == set(TYPES) and (live.mu >= 0).all()


def test_unknown_coarse_covariate_does_not_inflate_its_childrens_mu():
    from core.grid import parent

    f2, f10, X2, X10, cells = _setup("slowdown")
    hole = "10000_2_2"
    X10 = X10.assign(log_dist_coast=X10.log_dist_coast.where(X10.cell_id != hole))
    mu, _ = _glm(f2, f10, X2, X10)
    test = SPLIT.test(f2)
    kids = (test.cell_id.map(parent) == hole).to_numpy()
    rate = fake_sim.planted_rate(cells[cells.level == 2000].set_index("cell_id"))
    ratio = mu[kids].sum() / (test.cell_id[kids].map(rate) * test.exposure[kids]).sum()
    assert 0.5 < ratio < 2, ratio  # before the fix, M = 0 for that cell, so theta blew up


def test_backtest_leaves_out_a_fold_with_no_observed_rows():
    f2, f10, *_ = _setup("dark_small")
    fs = folds(f2.date.max().date(), 3)
    f2 = f2.copy()
    f2.loc[fs[0].test(f2).index, ["count", "exposure"]] = 0.0  # no calm pass in fold 1's week
    table = backtest(f2, fs, lambda s: _ewma(f2, f10, s))
    assert list(table.fold) == [2, 3]
