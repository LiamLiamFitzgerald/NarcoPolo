import numpy as np
import pytest
from statsmodels.stats.multitest import multipletests

from core import io
from core.config import load
from sim.simulate import simulate
from validate.power import _power, _power_block, _power_table, _sf


def test_power_gain_p01_vs_p04():
    """Empirical power of the window-total test, on counts drawn at the comparison rates, matches the exact value;
    BH over many null and a few raised cells keeps the false-discovery share at or below q."""
    cfg = load(io.CONFIG_PATH)[0]
    sim, v, q = cfg["sim"], cfg["validate"], cfg["p6"]["fdr_q"]
    alpha, days, reps = (
        float(v["power_alpha"]),
        28,
        20000,
    )  # 28 = a full four-week evaluation window
    rng = np.random.default_rng(cfg["seed"] + 351)
    powers = {}
    for p in sim["p_detect_scenarios"]:
        M = sim["baseline_rate"] * p * days
        for r in v["power_rate_ratios"]:
            exact = _power(np.array([M]), np.array([1.0]), r, alpha)[0]
            x = rng.poisson(r * M, reps)
            emp = float((_sf(x, M, 1.0) <= alpha).mean())
            assert abs(emp - exact) <= 4 * np.sqrt(exact * (1 - exact) / reps) + 1e-3, (
                p,
                r,
                emp,
                exact,
            )
            powers[p, r] = exact
    lo, hi = sorted(sim["p_detect_scenarios"])
    assert all(powers[hi, r] > powers[lo, r] for r in v["power_rate_ratios"])
    # overdispersed nulls: phi > 1 widens the tail, so the same raise is harder to flag
    M = sim["baseline_rate"] * hi * days
    assert _power(np.array([M]), np.array([3.0]), 3, alpha)[0] < powers[hi, 3]

    # BH: 950 null cells, 50 at rate ratio 3, false-discovery share averaged over runs <= q
    n0, n1, runs, M = 950, 50, 200, sim["baseline_rate"] * hi * days
    fdp = []
    for _ in range(runs):
        x = np.concatenate([rng.poisson(M, n0), rng.poisson(3 * M, n1)])
        flag = multipletests(_sf(x, M, 1.0), alpha=q, method="fdr_bh")[0]
        fdp.append(flag[:n0].sum() / max(flag.sum(), 1))
    assert np.mean(fdp) <= q


def test_power_nan_where_unobserved():
    assert np.isnan(_power(np.array([np.nan, 0.0]), np.array([1.0, 1.0]), 2, 0.001)).all()


@pytest.fixture(scope="module")
def sim_world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("w")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_RAW", str(tmp / "raw"))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    yield tmp
    mp.undo()


@pytest.mark.slow
def test_power_table_on_the_simulator(sim_world):
    exp, obs = io.read_stage("forecast/expected"), io.read_stage("aggregate/observed")
    t = _power_table(exp, obs, 0.001, [2.0, 3.0])
    fine = obs[(obs["level"] == 2000) & (obs["event_type"] == "dark_small")]
    assert set(t["cell_id"]) == set(fine["cell_id"])
    unseen = t["cell_days"] == 0
    assert (
        unseen.any() and t.loc[unseen, ["mu_per_day", "power_rr2", "power_rr3"]].isna().all().all()
    )
    seen = t[~unseen & (t["mu_window"] > 0)]
    assert seen["power_rr3"].between(0, 1).all() and (seen["power_rr3"] >= seen["power_rr2"]).all()
    block = _power_block()
    assert block["n_observed_cells"] == int(t["mu_window"].notna().sum())
    assert len(block["scenarios"]) == len(load(io.CONFIG_PATH)[0]["sim"]["p_detect_scenarios"])
    assert all(0 <= s <= 1 for s in block["share_with_power_at_least_min"].values())
