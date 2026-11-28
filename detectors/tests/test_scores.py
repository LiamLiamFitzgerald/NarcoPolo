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
from core.grid import cell_id, centroid
from detectors import bh, cusum, gi_star, pearson_z, tail_pmid
from detectors._common import PARAMS
from detectors.scores import _alarm_rate, _calibrate_h
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
    z = gi_star(C, mu, cells)
    assert cells[int(np.argmax(z))] in planted
    assert cells[int(np.argmax(z))] == cell_id(6, 6, 2000)  # centre has the most busy neighbours
    assert np.array_equal(z, gi_star(C, mu, cells))
    assert np.all(
        np.isfinite(gi_star(np.zeros(4), np.ones(4), cells[:4]))
    )  # flat week: z = 0, not NaN


def _gi_star_textbook(y, cells, band_m, row_standardise):
    """Ord & Getis (1995) Gi*, written the way esda.G_Local(star=True) computes Zs: a dense weight matrix with
    w_ii = 1, optionally row-standardised (esda's default transform 'R'), z = (G - E[G]) / sqrt(V[G])."""
    xy = np.array([centroid(c) for c in cells])
    d = np.hypot(*(xy[:, None, :] - xy[None, :, :]).transpose(2, 0, 1))
    w = (d <= band_m).astype(float)  # includes the diagonal (star)
    if row_standardise:
        w /= w.sum(axis=1, keepdims=True)
    n, W, S1 = len(y), w.sum(axis=1), (w**2).sum(axis=1)
    G = w @ y / y.sum()
    EG = W / n
    s2 = (y**2).sum() / n - y.mean() ** 2
    VG = (n * S1 - W**2) / (n - 1) * s2 / y.sum() ** 2
    return (G - EG) / np.sqrt(VG)


def test_gi_star_matches_the_textbook_formula_on_an_irregular_grid():
    # D6: an irregular set of observed cells (holes, an edge, an isolated cell), so neighbour counts differ
    rng = np.random.default_rng(3)
    cells = [c for c in _block(7) if rng.uniform() < 0.7] + [cell_id(20, 20, 2000)]
    C, mu = rng.poisson(2.0, len(cells)).astype(float), rng.uniform(0.5, 3, len(cells))
    y = (C + 0.5) / (mu + 0.5)
    z = gi_star(C, mu, cells, band_m=2900)
    for rs in (False, True):  # binary or row-standardised weights give the same z
        assert np.allclose(z, _gi_star_textbook(y, cells, 2900, rs))


def test_gi_star_matches_esda_when_installed():
    esda, libpysal = pytest.importorskip("esda"), pytest.importorskip("libpysal")
    rng = np.random.default_rng(4)
    cells = [c for c in _block(6) if rng.uniform() < 0.8]
    C, mu = rng.poisson(2.0, len(cells)).astype(float), rng.uniform(0.5, 3, len(cells))
    w = libpysal.weights.DistanceBand(
        np.array([centroid(c) for c in cells]), threshold=2900, silence_warnings=True
    )
    g = esda.G_Local((C + 0.5) / (mu + 0.5), w, star=True, permutations=0)
    assert np.allclose(gi_star(C, mu, cells, band_m=2900), g.Zs)


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


def test_cusum_h_is_calibrated_on_a_null_simulator_run(tmp_path, monkeypatch):
    # D2: on a null run (no drops), the configured h gives about the target false-alarm rate, and _calibrate_h
    # returns an h that meets the target while a slightly smaller one does not
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    cfg = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 1, regime="null")
    obs = io.read_stage("aggregate/observed")
    m = obs[obs["exposure"] > 0].merge(io.read_stage("forecast/expected"), on=KEY)
    series = [
        (g["count"].to_numpy(), g["mu"].to_numpy(), g["phi"].to_numpy())
        for _, g in m.sort_values("date").groupby(["event_type", "cell_id"])
    ]
    target = PARAMS["cusum_alarms_per_quarter"]
    h = _calibrate_h(series, target)
    assert _alarm_rate(series, h) <= target < _alarm_rate(series, h * 0.9)
    assert _alarm_rate(series, PARAMS["cusum_h"]) == pytest.approx(target, rel=0.1)
