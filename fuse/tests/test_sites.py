"""Issue 57: per-cell sites, suppression, site score, permutation, recurrence (simulator first)."""

import math
import shutil

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from core.grid import centroid
from fuse import permutation, recurrence, site_score, suppress
from fuse._common import PARAMS
from fuse.link import LinkTable, sites
from sim.simulate import simulate


def test_site_score_halves_every_half_life_and_skips_missing_L():
    assert site_score([1.0, np.nan], [0, 0]) == pytest.approx(1.0)
    assert site_score([1.0], [PARAMS["half_life_days"]]) == pytest.approx(0.5)
    assert site_score([], []) == 0.0


def test_recurrence_counts_links_above_the_median():
    assert recurrence([0.1, 0.5, 0.9, np.nan], 0.4) == 2


def _site(cid):
    x, y = centroid(cid)
    return {"site_id": cid, "x_m": x, "y_m": y}


def test_suppress_drops_2km_keeps_6km():
    from core.grid import cell_id

    a, near, far = cell_id(10, 10, 2000), cell_id(11, 10, 2000), cell_id(13, 10, 2000)
    out = suppress(pd.DataFrame([_site(a), _site(near), _site(far)]))
    assert out["site_id"].tolist() == [a, far]


def test_sites_one_row_per_cell_with_unobserved_counted():
    slow = pd.DataFrame(
        {
            "cell_id": ["c1", "c1", "c2"],
            "X": [1.0, 0.0, np.nan],
            "L": [0.6, np.nan, np.nan],
            "age_days": [0.0, 1.0, 5.0],
        }
    )
    from fuse import link

    mp = pytest.MonkeyPatch()
    mp.setattr(link, "centroid", lambda c: (0.0, 0.0))
    out = sites(slow).set_index("site_id")
    mp.undo()
    assert out.loc["c1", "n_slowdowns"] == 2 and out.loc["c1", "followup_unobserved"] == 1
    assert out.loc["c1", "S"] == pytest.approx(0.6) and out.loc["c2", "S"] == 0.0
    assert out.loc["c2", "n_slowdowns"] == 1  # no L, still counted


def _table(best_rows, n_days):
    cells = pd.Index([f"c{i}" for i in range(len(best_rows))])
    best = np.array(best_rows, float)
    return LinkTable(cells, pd.Timestamp("2026-01-01"), best, np.ones_like(best))


def test_permutation_seeded_and_finds_a_timed_link():
    """c0: its slowdowns land exactly on the one high-U day; c1: flat U, timing carries no information."""
    n_days = 120
    peak = np.full(n_days, 0.05)
    peak[[40, 70]] = 1.0
    flat = np.full(n_days, 0.3)
    table = _table([peak, flat], n_days)
    day = pd.Timestamp("2026-01-01")
    slow = pd.DataFrame(
        {
            "cell_id": ["c0", "c0", "c1", "c1"],
            "date": [day + pd.Timedelta(days=k) for k in (40, 70, 40, 70)],
            "U": 1.0,
        }
    )
    p1 = permutation(slow, table, seed=7)
    p2 = permutation(slow, table, seed=7)
    assert p1.equals(p2)  # same seed, same p
    assert p1["c0"] < 0.05 < p1["c1"]
    m = 2
    n = max(PARAMS["n_shuffles"], math.ceil(10 * m / PARAMS["fdr_q"]))
    assert p1["c0"] >= 1 / (n + 1)


def test_permutation_untested_sites_get_one():
    table = _table([np.full(30, -np.inf)], 30)
    slow = pd.DataFrame({"cell_id": ["c0"], "date": [pd.Timestamp("2026-01-05")], "U": 1.0})
    assert permutation(slow, table).tolist() == [1.0]


@pytest.fixture(scope="module")
def sim_sites(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p6sites")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    import fuse

    fuse.run()
    out = io.read_stage("fuse/sites"), pd.read_parquet(io.truth_path())
    yield out
    mp.undo()


def test_sim_sites_are_schema_valid_and_unique(sim_sites):
    s, _ = sim_sites
    assert len(s) > 0 and s["site_id"].is_unique
    assert (s["followup_unobserved"] <= s["n_slowdowns"]).all()


def _visible_pickups(frames, site):
    """Positive control: give each planted slowdown at `site` a seen pick-up (count 1, U 1) on the first observed
    dark_small day of its own cell within link_days, as if every pick-up had been caught on a calm pass."""
    obs, cells, ev = frames["obs"].copy(), frames["cells"].copy(), frames["events"]
    obs["date"] = pd.to_datetime(obs["date"])
    cells["date"] = pd.to_datetime(cells["date"])
    small = (obs["event_type"] == "dark_small") & (obs["cell_id"] == site) & (obs["exposure"] > 0)
    csmall = (cells["event_type"] == "dark_small") & (cells["cell_id"] == site)
    slow = ev[(ev["event_type"] == "slowdown") & (ev["cell_id"] == site)]
    days = pd.to_datetime(slow["time_utc"].dt.tz_convert("UTC").dt.date)
    for d in days:
        cand = obs.index[small & obs["date"].between(d, d + pd.Timedelta(days=PARAMS["link_days"]))]
        for i in cand:
            hit = csmall & (cells["date"] == obs.at[i, "date"])
            if hit.any():
                obs.loc[i, "count"] = max(1.0, obs.at[i, "count"])
                cells.loc[hit, "U"] = 1.0
                break
    return obs, cells


@pytest.fixture(scope="module")
def planted(tmp_path_factory):
    """Simulator run with the planted pick-ups made visible (positive control), scored by the pure path."""
    from fuse.link import _run

    tmp = tmp_path_factory.mktemp("p6plant")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    try:
        simulate(load(cfg)[0], 20261127)
        truth = pd.read_parquet(io.truth_path())
        site = str(truth.loc[truth["kind"] == "drop", "cell_id"].iloc[0])
        frames = {
            "obs": io.read_stage("aggregate/observed"),
            "cells": io.read_stage("fuse/cells"),
            "events": io.read_stage("match/events"),
        }
        obs, cells = _visible_pickups(frames, site)
        _, out = _run(
            obs, None, None, None, frames["events"], cells=cells, T=io.read_snapshot()["T"]
        )
    finally:
        mp.undo()
    return site, out


def test_busy_areas_are_not_flagged_and_planted_site_scores_high(planted):
    """Busy cells (most slowdowns, e.g. anchorages) get the largest S by sheer volume; the permutation test must
    keep them unflagged. The planted site, with its pick-ups seen, scores above the median tested site."""
    site, out = planted
    busiest = out.sort_values("n_slowdowns", ascending=False).head(3)
    assert not busiest["bh_flag"].any()
    tested = out[out["S"] > 0]
    assert out.loc[out["site_id"] == site, "S"].iloc[0] > tested["S"].median()


@pytest.mark.xfail(
    strict=True,
    reason="#177: one shared shift can only make as many shuffles as there are scored days (~40-120), so the "
    "smallest p (~0.01-0.02) can't pass BH even over the top 15; with a short history the planted site is a "
    "candidate (test_planted_site_is_a_patrol_candidate) but not the lowest p. Decision: options 1 + 3.",
)
def test_planted_site_has_lowest_p_perm_and_bh_flag(planted):
    site, out = planted
    top = out.sort_values("p_perm").iloc[0]
    assert top["site_id"] == site and bool(top["bh_flag"])


def test_planted_site_is_a_patrol_candidate(planted):
    """#177 decision (options 1 + 3): sites are tested only within the top-k by S, and a site needs no BH flag to be
    patrolled. Acceptance: with its pick-ups seen, the planted site is among the tested candidates, and the busy
    anchorages are not flagged."""
    site, out = planted
    tested = out[out["S"] > 0].sort_values("S", ascending=False).head(PARAMS["test_top_k"])
    assert site in set(tested["site_id"])
    assert not out.sort_values("n_slowdowns", ascending=False).head(3)["bh_flag"].any()
