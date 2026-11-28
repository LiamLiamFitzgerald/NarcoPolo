import json

import numpy as np
import pandas as pd
import pytest

from core.split import Split, folds
from forecast import (
    EXPECTED_COLUMNS,
    _pit_coverage,
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
    return glm_mu(split, split.train(f2), split.test(f2), X2)


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
    f2, f10, X2, _, _ = _setup(event_type)
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
    with pytest.raises(ValueError, match="look-ahead"):
        glm_mu(SPLIT, pd.concat([SPLIT.train(f2), leak]), SPLIT.test(f2), X2)


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
    seen = (test.exposure > 0).to_numpy()
    coverage = _pit_coverage(test["count"][seen], mu[seen], phi, LEVEL)
    assert abs(coverage - LEVEL) <= 0.02, coverage


def test_pit_coverage_recovers_known_nb_coverage():
    """D7 (#175): at small mu the raw "count in [lo, hi]" measure has a floor near P(0); PIT doesn't."""
    from scipy import stats

    rng = np.random.default_rng(20261127)
    phi, n = 2.0, 200_000
    for mu in (0.05, 5.0):
        c = stats.nbinom(n=mu / (phi - 1), p=1 / phi).rvs(n, random_state=rng)
        m = pd.Series(np.full(n, mu))
        lo, hi = nb_interval(m, phi, LEVEL)
        if mu == 0.05:
            assert ((c >= lo) & (c <= hi)).mean() >= 0.95  # the old measure, fooled by P(0)
        assert abs(_pit_coverage(c, m, phi, LEVEL) - LEVEL) <= 0.01, mu
    assert _pit_coverage(c, m, 4.0, LEVEL) > 0.92  # too-wide intervals are caught (power)


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


@pytest.mark.parametrize("event_type,k", [("dark_small", 6), ("slowdown", 12)])
def test_walk_forward_backtest_beats_flat_average(event_type, k):
    f2, f10, X2, X10, _ = _setup(event_type)
    T = f2.date.max()
    fs = folds(T.date(), k)
    skills = {
        "ewma": backtest(f2, fs, lambda s: _ewma(f2, f10, s), MIN_SE),
        "glm": backtest(f2, fs, lambda s: _glm(f2, f10, X2, X10, s)[0], MIN_SE),
    }
    for name, table in skills.items():
        print(event_type, name, table.skill.agg(["mean", "min", "max"]).round(4).to_dict())
    for table in skills.values():
        assert np.isfinite(table.skill).all() and (table.skill < 1).all()
    assert skills["glm"].skill.mean() > 0


def _frames(event_type, fine_frame=None):
    f2, f10, X2, _, _ = _setup(event_type, fine_frame)
    return f2, f10, X2


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

    spiked = (f2, to_coarse(Observed(f2)).frame, frames[2])
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
    "split": {"n_folds_slowdown": 12, "n_folds_small": 6, "test_days": 7},
    "radar_history_days": 90,
}


def _all_observed() -> tuple[pd.DataFrame, pd.DataFrame]:
    parts = []
    for et in TYPES:
        fine, coarse, _ = fake_sim.observed(et)
        parts += [fine.frame, coarse.frame]
    return pd.concat(parts, ignore_index=True), fake_sim.cells()


@pytest.mark.slow
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
    # fold 0 = the radar history (#269): every 2 km row from T - 89 .. T, once, for both types
    fine = observed[observed.level == 2000]
    live = fine[fine.date > T - pd.Timedelta(days=90)]
    assert (expected.fold == 0).sum() == len(live)
    assert not expected[expected.fold == 0].duplicated(["cell_id", "date", "event_type"]).any()
    assert report.chosen.sum() == 2 and not (tmp_path / "D.md").exists()  # forced: nothing recorded
    assert (report.nb2_alpha < 0.1).all()  # the fake simulator is Poisson: NB2 agrees with phi ~ 1
    print(report.round(3).to_string())


def test_undefined_skill_falls_back_to_ewma_and_records_nothing(tmp_path):
    from forecast import _choose_or_default

    decisions = tmp_path / "D.md"
    skills = {
        "ewma": pd.DataFrame({"fold": [1], "skill": [np.nan]}),
        "glm": pd.DataFrame({"fold": [1], "skill": [0.2]}),
    }
    assert _choose_or_default("dark_small", skills, str(decisions), "x") == "ewma"
    assert not decisions.exists()


@pytest.mark.slow
def test_p1_simulator_runs_through_both_p5_run_entry_points(tmp_path, monkeypatch):
    """make all's calls on sim.simulate's files: aggregate.run() then forecast.run()."""
    import aggregate
    import forecast
    from core.config import load
    from core.io import CONFIG_PATH, ROOT, read_stage
    from sim.simulate import simulate

    monkeypatch.setenv("NARCO_DATA", str(tmp_path))
    cfg, _ = load(CONFIG_PATH)
    simulate(cfg, cfg["seed"])
    log = ROOT / "DECISIONS.md"
    before = log.read_bytes()
    aggregate.run()
    obs = read_stage("aggregate/observed")
    assert set(obs.level) == {2000, 10000} and set(obs.event_type) == set(TYPES)
    forecast.run()
    expected = read_stage("forecast/expected")
    live = expected.query("fold == 0")
    assert set(live.event_type) == set(TYPES) and (live.mu >= 0).all()
    # D8 (#175): on the simulator, chosen on folds before the window: EWMA for slowdowns, GLM for dark_small
    choice = json.loads((tmp_path / "forecast" / "baseline_choice.json").read_text())
    chosen = {r["event_type"]: r["model"] for r in choice["models"] if r["chosen"]}
    assert chosen == {"slowdown": "ewma", "dark_small": "glm"}, choice
    assert all(r["select_folds"] > 0 and r["select_mean"] is not None for r in choice["models"])
    assert {et: set(g.model) for et, g in expected.groupby("event_type")} == {
        et: {m} for et, m in chosen.items()
    }
    # finite mu and phi wherever the cell was observed and its block had an observed day before it;
    # detectors divide by max(phi, 1). A live block with no history (#269) has no rows, never 0.
    fine = obs[obs.level == 2000].assign(date=lambda d: pd.to_datetime(d.date))
    seen_rows = fine.loc[fine.exposure > 0, ["cell_id", "date", "event_type"]]
    seen = expected.assign(date=pd.to_datetime(expected.date)).merge(seen_rows)
    first = seen_rows.groupby("event_type").date.min()
    from core.io import read_snapshot
    from forecast import _live_splits

    T = pd.Timestamp(read_snapshot()["T"])
    cut = pd.Series(pd.NaT, index=seen.index, dtype="datetime64[ns]")
    for s in _live_splits(T, cfg["radar_history_days"], cfg["split"]["test_days"]):
        inside = (seen.fold == 0) & seen.date.isin(s.test(seen).date)
        cut[inside] = pd.Timestamp(s.cutoff)
    blind = (seen.fold == 0) & (cut <= seen.event_type.map(first))
    assert len(seen) and np.isfinite(seen[["mu", "phi"]]).all().all() and not blind.any()
    # fold 0 spans the radar history (#269): every date for slowdowns (24 months before it); for
    # dark_small every date after the first block, which has no radar day before it
    live = expected[expected.fold == 0].assign(date=lambda d: pd.to_datetime(d.date))
    days = cfg["radar_history_days"]
    for et, g in live.groupby("event_type"):
        rows = fine[fine.event_type == et]
        want = set()
        for s in _live_splits(T, days, cfg["split"]["test_days"]):
            if (s.train(rows).exposure > 0).any():  # the block has an observed day before it
                want |= set(s.test(rows).date)
        assert set(g.date) == want, et
    assert live[live.event_type == "slowdown"].date.nunique() == days  # 24 months before it
    assert live.date.min() >= T - pd.Timedelta(days=days - 1) and live.date.max() == T
    assert log.read_bytes() == before  # simulated runs record no decision


@pytest.mark.slow
def test_report_coverage_skips_rows_whose_mu_is_unknown():
    """A cell with an unknown covariate has mu = NaN under the GLM; coverage must score the rest, not turn NaN."""
    from forecast import forecast_all

    observed, cells = _all_observed()
    cells.loc[cells.cell_id == "2000_3_3", "dist_coast_m"] = np.nan
    glm = {"slowdown": "glm", "dark_small": "glm"}
    _, report = forecast_all(observed, cells, observed.date.max(), CFG, None, "x", glm)
    assert np.isfinite(report.loc[report.chosen, "coverage"]).all(), report


def test_unknown_covariate_does_not_inflate_its_neighbours_mu():
    from core.grid import parent

    f2, f10, X2, X10, cells = _setup("slowdown")
    hole = "10000_2_2"
    unknown = (X2.cell_id.map(parent) == hole) & (
        X2.cell_id.str.split("_").str[1].astype(int) % 2 == 0
    )
    X2 = X2.assign(log_dist_coast=X2.log_dist_coast.where(~unknown))
    mu, _ = _glm(f2, f10, X2, X10)
    test = SPLIT.test(f2)
    known = ~test.cell_id.isin(X2.cell_id[unknown])
    kids = ((test.cell_id.map(parent) == hole) & known).to_numpy()
    rate = fake_sim.planted_rate(cells[cells.level == 2000].set_index("cell_id"))
    ratio = mu[kids].sum() / (test.cell_id[kids].map(rate) * test.exposure[kids]).sum()
    # before the fix, the unknown children's O counted but their M didn't, so theta blew up
    assert 0.5 < ratio < 2, ratio


def test_backtest_leaves_out_a_fold_with_no_observed_rows():
    f2, f10, *_ = _setup("dark_small")
    fs = folds(f2.date.max().date(), 3)
    f2 = f2.copy()
    f2.loc[fs[0].test(f2).index, ["count", "exposure"]] = 0.0  # no calm pass in fold 1's week
    table = backtest(f2, fs, lambda s: _ewma(f2, f10, s), MIN_SE)
    assert list(table.fold) == [2, 3]


def test_a_cell_with_no_events_yet_gets_a_small_rate_not_zero():
    f2, f10, *_ = _setup("dark_small")
    f2 = f2.assign(count=f2["count"].where(f2.cell_id != "2000_3_3", 0.0))
    mu = _ewma(f2, f10)
    test = SPLIT.test(f2)
    seen = ((test.cell_id == "2000_3_3") & (test.exposure > 0)).to_numpy()
    assert (mu[seen] > 0).all()  # before: rate 0, so one later event made the deviance infinite


def test_choose_baseline_records_nothing_without_a_path_and_no_repeats(tmp_path):
    decisions = tmp_path / "DECISIONS.md"
    glm_wins = {
        "ewma": pd.DataFrame({"fold": [1], "skill": [0.01]}),
        "glm": pd.DataFrame({"fold": [1], "skill": [0.05]}),
    }
    assert choose_baseline("slowdown", glm_wins, None, "t0") == "glm"
    assert not decisions.exists()
    for when in ("t1", "t2"):
        choose_baseline("slowdown", glm_wins, str(decisions), when)
    assert decisions.read_text().count("slowdown: glm") == 1  # same choice, written once
    ewma_wins = {"ewma": glm_wins["glm"], "glm": glm_wins["ewma"]}
    choose_baseline("slowdown", ewma_wins, str(decisions), "t3")
    assert decisions.read_text().count("slowdown: ewma") == 1  # a change is written


@pytest.mark.slow
def test_glm_is_fitted_once_per_fold(monkeypatch):
    import forecast
    from forecast import forecast_all

    calls = []
    real = forecast.glm_mu
    monkeypatch.setattr(forecast, "glm_mu", lambda *a: calls.append(1) or real(*a))
    observed, cells = _all_observed()
    forced = {"slowdown": "glm", "dark_small": "ewma"}
    forecast_all(observed, cells, observed.date.max(), CFG, None, "x", forced)
    # one fit per backtest fold for the comparison, plus each live block only where the GLM is chosen
    from forecast import _live_splits

    blocks = len(_live_splits(observed.date.max(), 90, 7))
    assert len(calls) == (12 + blocks) + 6


@pytest.mark.parametrize("event_type", TYPES)
def test_ewma_phi_is_finite_and_near_one_on_poisson_data(event_type):
    """The fake simulator is Poisson with constant rates, so Pearson X^2 / n of the EWMA is about 1."""
    from forecast import _ewma_phi

    f2, f10, *_ = _setup(event_type)
    phi = _ewma_phi(SPLIT, SPLIT.train(f2), SPLIT.train(f10), DELTA, MIN_SE)
    assert np.isfinite(phi) and phi == pytest.approx(1.0, abs=0.15), phi


def test_ewma_phi_sees_extra_variation():
    """Doubling every other day's counts adds variation the EWMA doesn't follow: phi must go up."""
    from forecast import _ewma_phi

    f2, f10, *_ = _setup("slowdown")
    noisy = f2.assign(count=f2["count"] * np.where(f2.date.dt.day % 2 == 0, 2.0, 0.0))
    phi = _ewma_phi(SPLIT, SPLIT.train(noisy), SPLIT.train(f10), DELTA, MIN_SE)
    assert phi > 1.5, phi


def test_ewma_rows_carry_the_ewma_phi_not_the_glm_phi():
    from forecast import _ewma_phi

    frames = _frames("slowdown")
    f2, f10, _ = frames
    rows = expected_rows("ewma", SPLIT, 1, frames, DELTA, MIN_SE, LEVEL, glm=(None, 99.0))  # type: ignore[arg-type]
    own = _ewma_phi(SPLIT, SPLIT.train(f2), SPLIT.train(f10), DELTA, MIN_SE)
    assert (rows.phi == own).all() and np.isfinite(rows.phi).all()


def test_choice_uses_only_folds_tested_before_the_evaluation_window():
    from forecast import _selection_folds

    for T in pd.date_range("2026-11-02", periods=7):  # every weekday the window can start on
        fs = folds(T.date(), 12)
        sel = _selection_folds(fs, T)
        window = evaluation_split(T)
        days = pd.DataFrame({"date": pd.date_range(T - pd.Timedelta(days=120), T)})
        for k, s in enumerate(fs, start=1):
            if k in sel:
                window.assert_train(s.test(days))  # no chosen-on day is in the window
            else:
                with pytest.raises(ValueError, match="look-ahead"):
                    window.assert_train(s.test(days))
        assert sel == list(range(sel[0], 13)) and sel[0] in (5, 6)


def test_a_wild_evaluation_window_does_not_change_the_choice():
    """Folds inside the window may score anything; the choice is made on the folds before it."""
    from forecast import forecast_all

    observed, cells = _all_observed()
    T = observed.date.max()
    _, before = forecast_all(observed, cells, T, CFG, None, "x")
    wild = observed.copy()
    inside = (wild.date >= pd.Timestamp(evaluation_split(T).cutoff)) & (wild.exposure > 0)
    wild.loc[inside, "count"] += 20
    _, after = forecast_all(wild, cells, T, CFG, None, "x")
    pd.testing.assert_series_equal(before.chosen, after.chosen)
    pd.testing.assert_series_equal(before.select_mean, after.select_mean)
    from forecast import _selection_folds

    n = {
        et: len(_selection_folds(folds(T.date(), k), T))
        for et, k in [("slowdown", 12), ("dark_small", 6)]
    }
    assert (before.select_folds == before.event_type.map(n)).all() and (
        before.select_folds > 0
    ).all()


def test_choose_baseline_keeps_ewma_unless_the_margin_is_beaten():
    skills = {
        "ewma": pd.DataFrame({"fold": [5, 6], "skill": [0.10, 0.10]}),
        "glm": pd.DataFrame({"fold": [5, 6], "skill": [0.14, 0.14]}),
    }
    assert choose_baseline("dark_small", skills, None, "x") == "glm"
    assert choose_baseline("dark_small", skills, None, "x", margin=0.05) == "ewma"
    assert choose_baseline("dark_small", skills, None, "x", margin=0.03) == "glm"


def test_model_by_type_in_config_fixes_the_model():
    from forecast import forecast_all

    observed, cells = _all_observed()
    cfg = {**CFG, "forecast": {"model_by_type": {"slowdown": "glm", "dark_small": "auto"}}}
    expected, _ = forecast_all(observed, cells, observed.date.max(), cfg, None, "x")
    assert set(expected[expected.event_type == "slowdown"].model) == {"glm"}
    bad = {**CFG, "forecast": {"model_by_type": "poisson"}}
    with pytest.raises(ValueError, match="unknown model"):
        forecast_all(observed, cells, observed.date.max(), bad, None, "x")


def test_a_fit_problem_is_one_log_line_not_a_warning(caplog):
    import warnings

    from forecast import _log_fit

    caught = [
        warnings.WarningMessage("x", UserWarning, "f", 1),
        warnings.WarningMessage("y", UserWarning, "f", 2),
    ]
    with caplog.at_level("WARNING", logger="forecast"), warnings.catch_warnings():
        warnings.simplefilter("error")
        _log_fit("GLM", SPLIT, caught, False, "10 rows")
        _log_fit("GLM", SPLIT, [], True, "10 rows")  # a clean fit says nothing
    assert len(caplog.records) == 1
    assert "did not converge for cutoff" in caplog.text and "UserWarning" in caplog.text


def test_live_blocks_cover_the_radar_history_once_each_fitted_before_its_dates():
    """#269: fold 0 = the evaluation window plus weekly blocks back to T - 89, no date twice or missing."""
    from forecast import _live_splits

    for T in pd.date_range("2026-11-02", periods=7):  # every weekday
        splits = _live_splits(T, 90, 7)
        days = pd.DataFrame({"date": pd.date_range(T - pd.Timedelta(days=120), T)})
        tested = pd.concat([s.test(days) for s in splits]).date
        assert splits[0] == evaluation_split(T)
        assert tested.is_unique and set(tested) == set(pd.date_range(T - pd.Timedelta(days=89), T))
        for s in splits:  # no embargo, and every training day is before every scored day
            assert s.embargo_days == 0 and s.train(days).date.max() < s.test(days).date.min()
            s.assert_train(s.train(days))
        assert all(1 <= s.test_days <= 7 for s in splits[1:])


@pytest.mark.parametrize("model", ["ewma", "glm"])
def test_a_live_block_never_sees_its_own_days(model):
    """Spiking one block's counts must not move that block's mu (nor any earlier block's)."""
    from aggregate import to_coarse
    from core.observed import Observed
    from forecast import _live_rows, _live_splits

    frames = _frames("dark_small")
    f2 = frames[0]
    T = f2.date.max()
    splits = _live_splits(T, 90, 7)
    params = (DELTA, MIN_SE, LEVEL)
    target = splits[3]
    spiked2 = f2.copy()
    inside = target.test(f2)
    spiked2.loc[inside.index[inside.exposure > 0], "count"] += 50  # observed rows only
    spiked = (spiked2, to_coarse(Observed(spiked2)).frame, frames[2])
    before = _live_rows(model, splits, frames, params)
    after = _live_rows(model, splits, spiked, params)
    same = before.date < pd.Timestamp(target.cutoff) + pd.Timedelta(days=target.test_days)
    pd.testing.assert_series_equal(before.mu[same], after.mu[same])
    assert not np.allclose(
        before.mu[~same], after.mu[~same], equal_nan=True
    )  # later blocks do learn


def test_a_live_block_with_no_history_is_unknown_not_zero():
    """dark_small history starts at T - 89: the oldest block has nothing before it, so it gets no rows."""
    from aggregate import to_coarse
    from core.observed import Observed
    from forecast import _live_rows, _live_splits

    f2, _, X2 = _frames("dark_small")
    T = f2.date.max()
    f2 = f2[f2.date > T - pd.Timedelta(days=90)]  # as aggregate writes it: radar_history_days only
    frames = (f2, to_coarse(Observed(f2)).frame, X2)
    splits = _live_splits(T, 90, 7)
    rows = _live_rows("glm", splits, frames, (DELTA, MIN_SE, LEVEL))
    blind = [s for s in splits if not (s.train(f2).exposure > 0).any()]
    assert splits[-1] in blind  # the oldest block starts with the history: nothing before it
    for s in splits:
        dates = set(s.test(f2).date)
        if s in blind:
            assert not rows.date.isin(dates).any()  # no rows: unknown, never mu = 0
        else:
            assert dates <= set(rows.date)
    assert np.isfinite(rows[["mu", "phi", "lo90", "hi90"]]).all().all()
