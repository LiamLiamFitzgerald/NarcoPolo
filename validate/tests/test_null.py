import sys
import types

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from core.grid import FINE, cell_id, cell_index
from sim.simulate import simulate
from validate.null import _NAMES, _shift, null_test


@pytest.fixture(scope="module")
def frames(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("n")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    mp.setenv("NARCO_RAW", str(tmp / "raw"))
    simulate(load(io.CONFIG_PATH)[0], 20261127)
    yield {k: io.read_stage(k) for k in _NAMES}
    mp.undo()


def _series(f, col):
    return f.groupby(["cell_id", "event_type"])[col].apply(lambda s: sorted(s.round(9)))


def test_shift_rotates_each_series_inside_the_date_range(frames):
    a = _shift(frames, np.random.default_rng(0))
    b = _shift(frames, np.random.default_rng(0))
    obs, new = frames["aggregate/observed"], a["aggregate/observed"]
    assert new.equals(b["aggregate/observed"]) and a["match/events"].equals(b["match/events"])
    assert set(new["date"]) == set(obs["date"])  # wraps, never leaves the range
    assert _series(new, "count").equals(_series(obs, "count"))  # each series keeps its values
    assert not (new["date"].to_numpy() == obs["date"].to_numpy()).all()  # but not their dates
    assert not ((new["count"] > 0) & (new["exposure"] <= 0)).any()  # counts move with exposure
    ev, t = a["match/events"], frames["match/events"]["time_utc"]
    assert ev["time_utc"].between(t.min().floor("D"), t.max().ceil("D")).all()
    assert (ev["time_utc"] != frames["match/events"]["time_utc"]).any()


def test_null_share_near_or_below_q(frames):
    first = null_test(runs=5, seed=0)
    if first["runs"] == 0:
        pytest.skip("fuse.run missing or still a stub (no cells)")
    # TODO(P1): fdr_q is not in config.yaml yet; 0.1 is the spec's q
    q = load(io.CONFIG_PATH)[0].get("p6", {}).get("fdr_q", 0.1)
    assert first["lo"] <= q  # shifting breaks the planted site
    assert null_test(runs=5, seed=0) == first


def test_null_loop_with_a_stand_in_fuse(frames, monkeypatch):
    """Stand-in for fuse.run: flag when a dark small boat follows a slowdown at the planted site within 4 days (the
    pick-up delay). Checks the loop (count, Wilson interval, A13 cut-back), not P6's statistics."""
    site = io.read_stage("fuse/sites").iloc[0]
    ix, iy = cell_index(site["x_m"], site["y_m"], FINE)
    cell = cell_id(int(ix), int(iy), FINE)

    def run(observed, expected, layers, travel, events, cells=None, T=None):
        t = events[events["cell_id"] == cell].assign(day=events["time_utc"].dt.floor("D"))
        slow, small = (t[t["event_type"] == e] for e in ("slowdown", "dark_small"))
        lag = (small["day"].to_numpy()[None, :] - slow["day"].to_numpy()[:, None]) / np.timedelta64(
            1, "D"
        )
        cells = pd.DataFrame({"cell_id": [cell]})  # non-empty: a real fuse, not the stub
        return cells, pd.DataFrame({"bh_flag": [bool(((lag >= 0) & (lag <= 4)).any())]})

    monkeypatch.setitem(sys.modules, "fuse", types.SimpleNamespace(run=run))
    out = null_test(runs=10, seed=0)
    assert out["runs"] == 10 and out == null_test(runs=10, seed=0)
    assert out["lo"] <= out["share_with_any_flag"] <= out["hi"]
    assert out["share_with_any_flag"] < 1  # shifting breaks the pairing in some runs
    monkeypatch.setattr("validate.null._BUDGET_S", 0.0)  # A13: a slow fuse.run means fewer runs
    assert null_test(runs=10, seed=0)["runs"] == 1
