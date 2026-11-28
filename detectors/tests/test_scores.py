"""Simulator tests for the three statistical detectors (issue 54)."""

import shutil
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from statsmodels.stats.multitest import multipletests

from core import io
from core.config import load
from core.grid import cell_id
from detectors import bh, cusum, gi_star, pearson_z, tail_pmid
from detectors._common import PARAMS
from sim.simulate import simulate

KEY = ["cell_id", "date", "event_type"]


@pytest.fixture(scope="module")
def sim_data(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p6s")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    yield load(cfg)[0]
    mp.undo()


def test_pearson_z():
    assert pearson_z([3.0, 1.0], [1.0, 4.0], [0.5, 4.0]).tolist() == [2.0, -0.75]


def test_tail_pmid_matches_scipy_for_integer_counts():
    C, mu = np.array([0.0, 1.0, 3.0, 7.0]), np.array([0.5, 1.2, 2.0, 3.0])
    pois = stats.poisson.sf(C, mu) + 0.5 * stats.poisson.pmf(C, mu)
    assert np.allclose(tail_pmid(C, mu, np.ones(4)), pois)
    assert np.allclose(tail_pmid(C, mu, np.full(4, 0.4)), pois)  # phi <= 1: Poisson
    phi = np.full(4, 2.5)
    n, p = mu / (phi - 1), 1 / phi
    assert np.allclose(stats.nbinom.mean(n, p), mu) and np.allclose(
        stats.nbinom.var(n, p), phi * mu
    )
    assert np.allclose(
        tail_pmid(C, mu, phi), stats.nbinom.sf(C, n, p) + 0.5 * stats.nbinom.pmf(C, n, p)
    )


def test_tail_pmid_soft_counts_interpolate_not_round():
    mu, phi = np.full(3, 0.3), np.array([1.0, 1.0, 3.0])
    lo = tail_pmid(np.zeros(3), mu, phi)
    hi = tail_pmid(np.ones(3), mu, phi)
    mid = tail_pmid(np.full(3, 0.4), mu, phi)
    assert np.all((mid < lo) & (mid > hi))  # 0.4 boats is weak evidence, not 0 boats
    assert np.allclose(mid, 0.6 * lo + 0.4 * hi)
    assert tail_pmid([0.0, 1.0], [0.0, 0.0], [1.0, 2.0]).tolist() == [0.5, 0.0]  # mu = 0 is defined


def test_bh_keeps_false_discovery_share_below_q():
    q = PARAMS["fdr_q"]
    fdp = []
    for seed in range(20):
        rng = np.random.default_rng(seed)
        truth = np.zeros(2000, bool)
        truth[:100] = True
        p = np.where(truth, rng.beta(0.05, 20, truth.size), rng.uniform(size=truth.size))
        flags = bh(p, q)
        assert flags[truth].mean() > 0.5  # it does find the signals
        fdp.append((flags & ~truth).sum() / max(flags.sum(), 1))
    assert np.mean(fdp) <= q
    p = np.random.default_rng(0).uniform(size=50) ** 3
    assert np.array_equal(bh(p, q), multipletests(p, alpha=q, method="fdr_bh")[0])
    assert bh([]).tolist() == []


def _block(n=12):
    return [cell_id(ix, iy, 2000) for ix in range(n) for iy in range(n)]


def test_gi_star_peaks_on_planted_cluster_and_is_deterministic():
    cells = _block()
    rng = np.random.default_rng(1)
    mu = np.full(len(cells), 1.0)
    C = rng.poisson(mu).astype(float)
    planted = [cell_id(ix, iy, 2000) for ix in (5, 6, 7) for iy in (5, 6, 7)]
    C[[cells.index(c) for c in planted]] += 6
    z = gi_star(C, mu, cells, seed=7)
    assert cells[int(np.argmax(z))] in planted
    assert cells[int(np.argmax(z))] == cell_id(6, 6, 2000)  # centre has the most busy neighbours
    assert np.array_equal(z, gi_star(C, mu, cells, seed=7))
    assert np.all(
        np.isfinite(gi_star(np.zeros(4), np.ones(4), cells[:4]))
    )  # flat week: z = 0, not NaN


def test_cusum_alarms_on_planted_build_up_and_unobserved_days_leave_s_unchanged():
    rho, h = PARAMS["cusum_rho"], PARAMS["cusum_h"]
    mu = np.full(20, 1.0)
    C = np.where(np.arange(20) >= 10, rho * mu, mu)  # rate doubles from day 10
    S = cusum(C, mu, np.ones(20))
    assert S[:10].max() <= h and S[10:].max() > h
    S = cusum([5.0, np.nan, np.nan, 0.0], [1.0, 1.0, 1.0, 1.0], [1.0] * 4, h=10)
    assert S[1] == S[2] == S[0]
    assert S[3] == S[0] - (rho - 1)  # C = 0 subtracts (rho - 1) mu
    assert cusum([2.0, 2.0], [1.0, 1.0], [4.0, 4.0], h=10)[0] == pytest.approx(
        (2 * np.log(rho) - 1) / 4
    )


def test_cusum_alarms_about_once_a_quarter_on_quiet_simulator_cells(sim_data):
    obs = io.read_stage("aggregate/observed")
    m = obs[obs["exposure"] > 0].merge(io.read_stage("forecast/expected"), on=KEY)
    quiet = m[(m["event_type"] == "slowdown") & (m["mu"] == sim_data["sim"]["slowdown_rate_cold"])]
    alarms = 0
    for _, g in quiet.sort_values("date").groupby("cell_id"):
        S = cusum(g["count"].to_numpy(), g["mu"].to_numpy(), g["phi"].to_numpy())
        alarms += int((S > PARAMS["cusum_h"]).sum())
    per_quarter = alarms / len(quiet) * 91
    assert 0.5 <= per_quarter <= 1.5


def test_run_cells_scores_only_observed_rows_in_the_evaluation_window(sim_data):
    import detectors

    detectors.run()
    cells = io.read_stage("fuse/cells")
    obs = io.read_stage("aggregate/observed")
    T = io.read_snapshot()["T"]
    start = T - timedelta(days=T.weekday() + 21)
    d = pd.to_datetime(cells["date"])
    assert d.min() >= pd.Timestamp(start) and d.max() <= pd.Timestamp(T)
    seen = obs[obs["exposure"] > 0][KEY].astype(str)
    assert len(cells) > 0 and cells[KEY].astype(str).merge(seen).shape[0] == len(cells)
    assert np.array_equal(cells["bh_flag"], bh(cells["p_mid"]))  # BH once over the whole window
    week = pd.to_datetime(cells["date"]).dt.isocalendar().week
    assert (
        cells.groupby(["event_type", "cell_id", week])["gi_z"].nunique() == 1
    ).all()  # a day gets its week's z


def test_score_cells_is_the_pure_core_of_run_cells(
    tmp_path, monkeypatch
):  # #177: the null test calls it
    import shutil

    from core import io
    from core.config import load
    from detectors import score_cells
    from sim.simulate import simulate

    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    cfg = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 7)
    frames = [
        io.read_stage(n)
        for n in ("aggregate/observed", "forecast/expected", "reference/cells", "match/events")
    ]
    a = score_cells(*frames, io.read_snapshot()["T"])
    b = score_cells(*frames, io.read_snapshot()["T"])
    assert len(a) and a.equals(b) and {"U", "agreement", "y", "y_week"} <= set(a.columns)


def test_gi_star_matches_esda_on_a_small_grid():
    """D6 (#174): our Gi* z is esda.G_Local(star=True).Zs with binary distance-band weights, self included."""
    esda = pytest.importorskip("esda")
    libpysal = pytest.importorskip("libpysal")
    from core.grid import centroid

    rng = np.random.default_rng(7)
    cells = [
        cell_id(ix, iy, 2000) for ix in range(6) for iy in range(5) if (ix, iy) != (2, 3)
    ]  # one gap
    C, mu = rng.poisson(4, len(cells)).astype(float), rng.uniform(2, 6, len(cells))
    C[[3, 11]] += 15  # a hotspot, so z is not all near 0
    y = (C + 0.5) / (mu + 0.5)
    w = libpysal.weights.DistanceBand(
        np.array([centroid(c) for c in cells]),
        threshold=PARAMS["gi_band_m"],
        binary=True,
        silence_warnings=True,
    )
    ref = esda.G_Local(y, w, transform="B", star=True, permutations=0).Zs
    assert gi_star(C, mu, cells) == pytest.approx(ref, abs=1e-6)


def _null_inc(mu, days=2000, cells=40, seed=0):
    rng = np.random.default_rng(seed)
    C = rng.poisson(mu, (cells, days)).astype(float)
    return [(c, np.full(days, mu), np.ones(days)) for c in C]


def test_calibrated_h_is_the_smallest_meeting_the_alarm_target():
    from detectors.scores import _alarm_rate, _calibrate_h

    series = _null_inc(0.3)
    h = _calibrate_h(series, per_days=91)
    assert h is not None and _alarm_rate(series, h) <= 1 / 91
    assert _alarm_rate(series, h - 1e-3) > 1 / 91  # any smaller h alarms too often


def test_calibrated_h_needs_more_than_one_event_on_a_quiet_cell():
    """Known answer: mu = 0.05 a day, so one event (+ ln 2 - 0.05) happens about every 20 days. Once a quarter
    needs h above a single event's increment."""
    from detectors.scores import _calibrate_h

    assert _calibrate_h(_null_inc(0.05), per_days=91) >= np.log(2) - 0.05


def test_unobserved_days_count_neither_as_days_nor_alarms():
    from detectors.scores import _alarm_rate

    c = np.array([3.0, np.nan, np.nan, 0.0])
    assert _alarm_rate([(c, np.ones(4), np.ones(4))], h=0.1) == pytest.approx(
        1 / 2
    )  # 1 alarm, 2 observed days


def test_a_target_that_never_binds_returns_none_not_a_zero_threshold():
    from detectors.scores import _calibrate_h

    assert (
        _calibrate_h(_null_inc(0.001), per_days=91) is None
    )  # single events far rarer than once a quarter
