"""Simulator tests for the lag link: follow-up exposure, link table, link score (issue 56)."""

import math
import shutil
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from core.grid import FINE, centroid, neighbours
from fuse import followup_exposure, link_score, link_table
from fuse._common import PARAMS
from fuse.link import _exposure, _link_slowdowns, _lookup, _radar, _u_small
from sim.simulate import simulate


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p6link")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    names = ["fuse/cells", "aggregate/observed", "match/events"]
    yield {n: io.read_stage(n) for n in names} | {"T": io.read_snapshot()["T"]}
    mp.undo()


@pytest.fixture(scope="module")
def grid(sim):
    """Simulator cell ids, a slowdown cell, one neighbour within 4 km and one cell beyond it."""
    obs = sim["aggregate/observed"]
    ids = sorted(obs.loc[obs["level"] == FINE, "cell_id"].unique())
    nbrs = neighbours(ids, PARAMS["link_radius_m"])
    c = next(c for c in ids if len(nbrs[c]) >= 8)
    near = nbrs[c][0]
    cx, cy = centroid(c)
    far = next(o for o in ids if 4000 < math.hypot(centroid(o)[0] - cx, centroid(o)[1] - cy) < 8000)
    return ids, nbrs, c, near, far


D0 = pd.Timestamp("2026-10-01")


def _frames(rows):
    """Tiny dark_small observed and fuse/cells frames from (cell, day offset, count, exposure, U) rows."""
    obs = pd.DataFrame(
        [
            {
                "cell_id": c,
                "level": FINE,
                "date": D0 + timedelta(days=k),
                "event_type": "dark_small",
            }
            | {"count": n, "exposure": e}
            for c, k, n, e, _ in rows
        ]
    )
    cells = obs[obs["exposure"] > 0].assign(U=[u for *_, e, u in rows if e > 0])
    return obs, cells


def _slowdown(c, k=0, U=0.8):
    return {"cell_id": c, "date": D0 + timedelta(days=k), "U": U}


def test_planted_visit_two_days_later_within_4km_gets_the_hand_computed_L(grid):
    _, nbrs, c, near, far = grid
    obs, cells = _frames(
        [
            (near, 2, 1.0, 1.0, 0.9),  # the planted visit
            (c, 5, 1.0, 1.0, 0.95),  # later and so more decayed: 0.95 e^(-5/3) < 0.9 e^(-2/3)
            (far, 1, 1.0, 1.0, 1.0),  # beyond 4 km: not in N
            (near, 9, 1.0, 1.0, 1.0),  # after the 7-day window
        ]
    )
    U, E = _u_small(cells, obs), _exposure(obs)
    want = 0.8 * 0.9 * math.exp(-2 / 3)
    assert link_score(_slowdown(c), U, nbrs) == pytest.approx(want)
    assert (
        followup_exposure(_slowdown(c), E, nbrs) == 2.0
    )  # near day 2 + c day 5; far and day 9 left out
    best, X = _lookup(link_table(U, E, nbrs), [c], pd.DatetimeIndex([D0]))
    assert 0.8 * best[0] == pytest.approx(want) and X[0] == 2.0


def test_zero_followup_exposure_gives_none_never_zero(grid):
    _, nbrs, c, near, _ = grid
    obs, cells = _frames(
        [(near, 3, 0.0, 0.0, 0.0), (near, 10, 1.0, 1.0, 0.9)]
    )  # only seen after the window
    U, E = _u_small(cells, obs), _exposure(obs)
    assert followup_exposure(_slowdown(c), E, nbrs) == 0.0
    assert link_score(_slowdown(c), U, nbrs) is None
    links = _link_slowdowns(
        pd.concat([cells, _slow_cells([c])]), obs, _events([c]), D0 + timedelta(days=20)
    )
    assert links["X"].iloc[0] == 0.0 and np.isnan(
        links["L"].iloc[0]
    )  # follow-up unobserved, L missing


def test_followup_of_only_quiet_observed_days_gets_L_zero(grid):
    _, nbrs, c, near, _ = grid
    # observed, nothing seen; the tied-rank U of 0.45 must not count (A5)
    obs, cells = _frames([(near, 1, 0.0, 1.0, 0.45), (c, 4, 0.0, 0.6, 0.45)])
    U, E = _u_small(cells, obs), _exposure(obs)
    assert followup_exposure(_slowdown(c), E, nbrs) == pytest.approx(1.6)
    assert link_score(_slowdown(c), U, nbrs) == 0.0  # we looked and nothing came


def test_same_day_pickup_is_linked_without_decay(grid):
    _, nbrs, c, near, _ = grid
    obs, cells = _frames(
        [(near, 0, 1.0, 1.0, 0.7), (near, -1, 1.0, 1.0, 1.0)]
    )  # the day before is not a follow-up
    U, E = _u_small(cells, obs), _exposure(obs)
    assert link_score(_slowdown(c), U, nbrs) == pytest.approx(0.8 * 0.7)
    assert followup_exposure(_slowdown(c), E, nbrs) == 1.0


def _events(cells, k=0):
    return pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(len(cells))],
            "event_type": "slowdown",
            "time_utc": pd.Timestamp(D0 + timedelta(days=k), tz="UTC") + timedelta(hours=12),
            "cell_id": cells,
        }
    )


def _slow_cells(cells, k=0, U=0.8):
    return pd.DataFrame(
        {"cell_id": cells, "date": D0 + timedelta(days=k), "event_type": "slowdown", "U": U}
    )


@pytest.mark.slow
def test_table_lookup_equals_direct_link_score_for_every_simulator_slowdown(sim):
    cells, obs, ev, T = sim["fuse/cells"], sim["aggregate/observed"], sim["match/events"], sim["T"]
    links = _link_slowdowns(cells, obs, ev, T)
    slow = ev[ev["event_type"] == "slowdown"]
    assert len(links) == len(slow) > 0
    assert links["L"].notna().any() and (links["X"] == 0).any()  # both kinds occur on the simulator
    ids = sorted(obs.loc[obs["level"] == FINE, "cell_id"].unique())
    nbrs = neighbours(ids, PARAMS["link_radius_m"])
    U, E = _radar(_u_small(cells, obs), T), _radar(_exposure(obs), T)
    assert (
        links["X"].isna().any()
    )  # the simulator's 120 days are longer than the 90-day radar history
    for s in links[links["X"].notna()].to_dict("records"):
        direct = link_score(s, U, nbrs)
        assert followup_exposure(s, E, nbrs) == pytest.approx(s["X"])
        if direct is None:
            assert np.isnan(s["L"]) and s["X"] == 0
        else:
            assert s["L"] == pytest.approx(direct) and 0 <= s["L"] <= 1
    assert (links["age_days"] >= 0).all()


def test_slowdown_whose_window_misses_the_radar_history_gets_no_X_and_no_L(grid):
    _, _, c, near, _ = grid
    obs, cells = _frames([(near, 0, 1.0, 1.0, 0.9)])
    ev, sc = (
        _events([c], k=-8),
        _slow_cells([c], k=-8),
    )  # window [day -8, day -1] ends before radar starts
    links = _link_slowdowns(pd.concat([cells, sc]), obs, ev, D0 + timedelta(days=5))
    assert np.isnan(links["X"].iloc[0]) and np.isnan(links["L"].iloc[0])
    ev, sc = (
        _events([c], k=-7),
        _slow_cells([c], k=-7),
    )  # window reaches day 0: linked, 7 days of decay
    L = _link_slowdowns(pd.concat([cells, sc]), obs, ev, D0 + timedelta(days=5))["L"].iloc[0]
    assert L == pytest.approx(0.8 * 0.9 * math.exp(-7 / 3))


def test_unobserved_rows_before_the_radar_history_do_not_count_as_followup_unobserved(grid):
    _, _, c, near, _ = grid
    # E = 0 dark_small rows 100 days back (outside T - 89 .. T): the slowdown there is out of range, not X = 0
    obs, cells = _frames([(near, -100, 0.0, 0.0, 0.0), (near, 0, 1.0, 1.0, 0.9)])
    ev, sc = _events([c], k=-100), _slow_cells([c], k=-100)
    links = _link_slowdowns(pd.concat([cells, sc]), obs, ev, D0 + timedelta(days=5))
    assert np.isnan(links["X"].iloc[0])


def test_link_rows_carry_no_ship_identity(sim):
    links = _link_slowdowns(
        sim["fuse/cells"], sim["aggregate/observed"], sim["match/events"], sim["T"]
    )
    assert "ship_key" not in links.columns
    assert list(links.columns) == ["event_id", "cell_id", "date", "U", "X", "L", "age_days"]
