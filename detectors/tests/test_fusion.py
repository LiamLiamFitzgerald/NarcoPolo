"""Simulator tests for the context rules, rank fusion and fuse/cells.parquet (issue 55)."""

import shutil

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from detectors import context_slowdown, context_small, fuse
from detectors._common import PARAMS
from detectors.scores import _ranks
from sim.simulate import simulate

NAN = np.nan


@pytest.fixture(scope="module")
def cells(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p6f")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    import detectors

    detectors.run()
    first = io.stage_path("fuse/cells").read_bytes()
    detectors.run()
    yield io.read_stage("fuse/cells"), first == io.stage_path("fuse/cells").read_bytes()
    mp.undo()


def test_context_small_leaves_unknown_facts_out_of_the_mean():
    layers = pd.DataFrame(
        {"inshore_frac": [0.0, NAN, 0.5, NAN], "dist_coast_m": [10000.0, 10000.0, 1000.0, 30000.0]}
    )
    got = context_small(layers, [1.0, NAN, 0.0, NAN])
    # row 1: no inshore map, storm unknown -> the coast fact alone; row 3: only the coast fact, which is no
    assert got.tolist() == [1.0, 1.0, 0.0, 0.0]
    assert context_small(layers.iloc[:1], [NAN])[0] == 1.0  # NaN storm is not "no storm"


def test_context_slowdown_uses_lane_and_slow_hours():
    layers = pd.DataFrame({"lane": [False, False, True, True]})
    got = context_slowdown(layers, [1.0, 5.0, NAN, 0.33])
    assert got.tolist() == [1.0, 0.5, 0.0, 0.5]


def _scores(n=50, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "event_type": np.repeat(["dark_small", "slowdown"], n),
            "p_mid": rng.uniform(size=2 * n),
            "gi_z": rng.normal(size=2 * n),
            "cusum_s": np.where(rng.uniform(size=2 * n) < 0.7, 0.0, rng.exponential(size=2 * n)),
            "context": rng.choice([0.0, 0.5, 1.0], 2 * n),
        }
    )


def test_all_four_ranks_share_one_row_set_per_event_type():
    s = _scores()
    r = _ranks(s)
    assert r.notna().all().all()
    for _, g in r.groupby(s["event_type"]):
        # ranks of a column without ties are exactly 1/n .. 1 over the same n rows
        assert np.allclose(np.sort(g["gi_z"]) * len(g), np.arange(1, len(g) + 1))
        assert np.allclose(np.sort(g["p_mid"]) * len(g), np.arange(1, len(g) + 1))
        assert np.allclose(
            g.sum(), (len(g) + 1) / 2
        )  # average ties keep the sum: every column saw n rows
    s.loc[3, "context"] = NAN
    with pytest.raises(ValueError):
        _ranks(s)


def test_fuse_ranks_small_p_high_and_counts_agreement():
    s = _scores()
    s.loc[0, ["p_mid", "gi_z", "cusum_s"]] = [1e-9, 10.0, 50.0]
    s.loc[0, "context"] = 1.0  # tied with a third of the rows, so not in context's own top 10%
    U, agreement = fuse(s)
    assert U[0] == U[:50].max() and agreement[0] == 3
    assert ((U >= 0) & (U <= 1)).all() and ((agreement >= 0) & (agreement <= 4)).all()
    r = _ranks(s)
    assert np.array_equal(agreement, (r > 1 - PARAMS["top_frac"]).sum(axis=1))


def test_run_cells_schema_ranges_and_same_seed_same_file(cells):
    c, identical = cells
    assert identical
    assert c["U"].between(0, 1).all() and c["agreement"].between(0, 4).all()
    assert c["context"].between(0, 1).all()


def test_backtest_fold_rows_never_duplicate_a_cell_day(cells):
    import detectors

    c, _ = cells
    exp = io.read_stage("forecast/expected")
    backtest = exp.assign(fold=pd.array([1] * len(exp), "Int64"), mu=exp["mu"] * 3)
    io.write_stage("forecast/expected", pd.concat([exp, backtest], ignore_index=True), "simulated")
    detectors.run()
    again = io.read_stage("fuse/cells")
    assert not again.duplicated(["cell_id", "date", "event_type"]).any()
    pd.testing.assert_frame_equal(again, c)  # fold 1 rows are ignored, not mixed in


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    """Seed 1 has planted drops inside the evaluation window; since drops come at irregular times (#163), the
    default seed's last drop falls before it (#197)."""
    tmp = tmp_path_factory.mktemp("p6p")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_RAW", str(tmp / "raw"))
    simulate(load(io.CONFIG_PATH)[0], 1)
    import detectors

    detectors.run()
    yield io.read_stage("fuse/cells"), pd.read_parquet(io.truth_path())
    mp.undo()


def test_planted_drop_cell_days_are_top_decile_with_agreement(planted):
    c, truth = planted
    drops = truth[truth["kind"] == "drop"].assign(date=lambda t: t["time_utc"].dt.date)
    slow = c[c["event_type"] == "slowdown"].assign(date=lambda t: pd.to_datetime(t["date"]).dt.date)
    hit = slow.merge(drops[["cell_id", "date"]], on=["cell_id", "date"])
    assert len(hit) > 0
    assert (hit["U"] >= slow["U"].quantile(0.9)).all()
    assert (hit["agreement"] >= 2).all()
