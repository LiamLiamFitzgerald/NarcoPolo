"""The simulator's stand-in Gi* and CUSUM (#167): known answers on small inputs, and signal at the planted site."""

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from sim._scores import cusum, gi_star
from sim.simulate import simulate


def test_cusum_accumulates_excess_and_resets_after_h():
    cell = np.array(["a"] * 4 + ["b"] * 2)
    kind = np.array(["slowdown"] * 6)
    day = np.array([0, 1, 2, 3, 0, 1])
    c = np.array([1.0, 1.0, 0.0, 1.0, 0.0, 0.0])
    mu = np.full(6, 0.1)
    s = cusum(cell, kind, day, c, mu, rho=2.0, h=1.0)
    inc = np.log(2) - 0.1
    assert s[0] == pytest.approx(inc) and s[1] == pytest.approx(2 * inc)  # 1.19 > h: reset after
    assert s[2] == 0.0 and s[3] == pytest.approx(inc)  # restarted from 0 (0 - 0.1 floors at 0)
    assert (s[4:] == 0).all()  # cell b never exceeds its expectation


def test_cusum_follows_day_order_not_row_order():
    args = (np.array(["a", "a"]), np.array(["slowdown"] * 2), np.array([1, 0]))
    s = cusum(*args, np.array([0.0, 2.0]), np.full(2, 0.1), rho=2.0, h=10.0)
    assert s[1] == pytest.approx(2 * np.log(2) - 0.1)  # day 0 first
    assert s[0] == pytest.approx(s[1] - 0.1)  # day 1 adds 0 - 0.1


def test_gi_star_is_highest_at_a_hot_cell_and_zero_when_flat():
    cells = np.array([f"2000_{i}_{j}" for i in range(5) for j in range(5)])
    n = len(cells)
    kind, week = np.array(["dark_small"] * n), np.array(["W1"] * n)
    c = np.zeros(n)
    c[12] = 5.0  # centre cell 2000_2_2
    z = gi_star(cells, kind, week, c, np.full(n, 0.1), band_m=2900)
    assert (
        z[12] == pytest.approx(z.max()) and z[12] > 1
    )  # every cell whose band holds the spike ties
    assert (gi_star(cells, kind, week, np.zeros(n), np.full(n, 0.1), 2900) == 0).all()


def test_simulated_cells_carry_gi_and_cusum_signal_at_the_planted_site(tmp_path, monkeypatch):
    """CUSUM alarms once per planted drop at the site and ranks it in the top 5% of cells by alarms; its Gi* peaks
    above 1.96. (Gi* smooths over the 8 neighbours, so a one-cell site need not rank first.)"""
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    cfg = load(io.CONFIG_PATH)[0]
    simulate(cfg, 1)
    cells = io.read_stage("fuse/cells")
    drops = pd.read_parquet(io.truth_path()).query("kind == 'drop'")
    site = drops["cell_id"].iloc[0]
    assert cells["gi_z"].nunique() > 1 and cells["cusum_s"].nunique() > 1
    slow = cells[cells["event_type"] == "slowdown"]
    alarms = slow.assign(a=slow["cusum_s"] > cfg["p6"]["cusum_h"]).groupby("cell_id")["a"].sum()
    assert alarms[site] >= 0.8 * len(drops)
    assert alarms.rank(ascending=False)[site] <= 0.05 * len(alarms)
    assert slow.loc[slow["cell_id"] == site, "gi_z"].max() > 1.96


def test_simulated_links_are_dated_at_their_slowdowns(tmp_path, monkeypatch):
    """#167: one link per planted slowdown, aged from its day to T; L = 1 where a pick-up followed it."""
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    cfg = load(io.CONFIG_PATH)[0]
    simulate(cfg, 1)
    links, sites = io.read_stage("fuse/links"), io.read_stage("fuse/sites")
    drops = pd.read_parquet(io.truth_path()).query("kind == 'drop'")
    assert len(links) == len(drops) and links["age_days"].nunique() > 1
    assert links["age_days"].between(0, cfg["sim"]["days"]).all()
    assert links["L"].sum() == sites["recurrence"].sum()  # every pick-up follows one slowdown
