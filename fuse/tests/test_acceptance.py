"""Issue 60: P6's "done when" list end to end on the simulator, detectors.run_cells -> fuse.run, with known truth.

Seeds 1 and 3 see at least one planted pick-up on a calm pass; seed 2 sees none. Tests import detectors and
validate, which tach allows in tests only (tach.toml excludes **/tests)."""

import shutil
import time

import pandas as pd
import pytest

from core import io
from core.config import load
from core.grid import FINE
from fuse._common import PARAMS
from sim.simulate import simulate

SEEN, UNSEEN = (1, 3), (2,)
_NAMES = (
    "aggregate/observed",
    "forecast/expected",
    "reference/cells",
    "reference/travel_hours",
    "match/events",
)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """Per seed: the written stage files (as frames), the planted site and how long one fuse.run took."""
    import detectors
    import fuse

    out = {}
    for seed in SEEN + UNSEEN:
        tmp = tmp_path_factory.mktemp(f"p6acc{seed}")
        mp = pytest.MonkeyPatch()
        mp.setenv("NARCO_DATA", str(tmp / "data"))
        mp.setenv("NARCO_REPORTS", str(tmp / "reports"))
        cfg = tmp / "config.yaml"
        shutil.copy(io.ROOT / "config.yaml", cfg)
        mp.setattr(io, "CONFIG_PATH", cfg)
        try:
            simulate(load(cfg)[0], seed)
            detectors.run_cells()
            tic = time.perf_counter()
            fuse.run()
            secs = time.perf_counter() - tic
            truth = pd.read_parquet(io.truth_path())
            frames = {n: io.read_stage(n) for n in _NAMES + ("fuse/cells", "fuse/sites")}
            out[seed] = {
                "frames": frames,
                "site": str(truth.loc[truth["kind"] == "drop", "cell_id"].iloc[0]),
                "seen": int(truth.loc[truth["kind"] == "pickup", "detected"].sum()),
                "T": io.read_snapshot()["T"],
                "secs": secs,
            }
        finally:
            mp.undo()
    return out


def _sites(r):
    return r["frames"]["fuse/sites"]


def test_simulator_seeds_cover_seen_and_unseen_pickups(runs):
    assert all(runs[s]["seen"] > 0 for s in SEEN) and all(runs[s]["seen"] == 0 for s in UNSEEN)


@pytest.mark.parametrize("seed", SEEN)
def test_planted_site_is_a_patrol_candidate_when_a_pickup_is_seen(runs, seed):
    """#177 decision: a site is patrolled from the top-k candidates by S (p_site and the bandit pick among them); it
    needs no BH flag. With one of its pick-ups seen, the planted site must be a candidate."""
    r = runs[seed]
    top = _sites(r).sort_values("S", ascending=False).head(PARAMS["test_top_k"])
    assert r["site"] in set(top["site_id"])


@pytest.mark.parametrize("seed", UNSEEN)
def test_unseen_drop_site_stays_listed_and_unflagged(runs, seed):
    """No pick-up seen: nothing to link, so the planted site must not be flagged, but it must stay in fuse/sites
    with its slowdowns (suppression may not hide it behind a quieter neighbour with the same S)."""
    s = _sites(runs[seed]).set_index("site_id")
    site = runs[seed]["site"]
    assert site in s.index and s.at[site, "n_slowdowns"] > 1 and not s.at[site, "bh_flag"]


@pytest.mark.parametrize("seed", SEEN + UNSEEN)
def test_busy_areas_without_a_planted_link_are_not_flagged(runs, seed):
    s = _sites(runs[seed])
    busiest = (
        s[s["site_id"] != runs[seed]["site"]].sort_values("n_slowdowns", ascending=False).head(3)
    )
    assert not busiest["bh_flag"].any()


@pytest.mark.parametrize("seed", SEEN + UNSEEN)
def test_flagged_sites_have_reasons_and_a_pier_or_say_none(runs, seed):
    s = _sites(runs[seed])
    for _, row in s[s["bh_flag"]].iterrows():
        assert len(row["reasons"]) > 0
        assert len(row["top_piers"]) > 0 or any(
            "pier within reach" in x.lower() for x in row["reasons"]
        )


def _rerun(r, events=None, observed=None, cells=None):
    from fuse.link import _all

    f = r["frames"]
    obs = f["aggregate/observed"] if observed is None else observed
    ev = f["match/events"] if events is None else events
    c = f["fuse/cells"] if cells is None else cells
    args = (obs, f["forecast/expected"], f["reference/cells"], f["reference/travel_hours"], ev)
    return _all(*args, cells=c, T=r["T"])[0].set_index("site_id")


def test_planted_slowdown_with_no_visit_is_not_flagged(runs):
    """A slowdown planted where no small boat is ever seen within 4 km: it gets no link (S = 0), so it can never be
    tested or flagged. Checked before suppression too, since a neighbour may show it as "nearby"."""
    from core.grid import neighbours
    from fuse.link import _link_slowdowns, sites

    r = runs[SEEN[0]]
    f = r["frames"]
    obs, ev = f["aggregate/observed"], f["match/events"]
    small = obs[(obs["event_type"] == "dark_small") & (obs["level"] == FINE)]
    C = small.groupby("cell_id")["count"].sum()
    nbrs = neighbours(sorted(C.index), PARAMS["link_radius_m"])
    quiet = [c for c in C.index if C[[c, *nbrs[c]]].sum() == 0 and c not in set(ev["cell_id"])]
    assert quiet, "no cell on the simulator without small boats within 4 km"
    cell = quiet[len(quiet) // 2]
    t = pd.Timestamp(r["T"], tz="UTC") - pd.Timedelta(days=20) + pd.Timedelta(hours=12)
    row = (
        ev[ev["event_type"] == "slowdown"]
        .iloc[[0]]
        .assign(event_id="planted-lonely", cell_id=cell, time_utc=t)
    )
    ev2 = pd.concat([ev, row], ignore_index=True)
    pre = sites(_link_slowdowns(f["fuse/cells"], obs, ev2, r["T"])).set_index("site_id")
    assert pre.at[cell, "n_slowdowns"] == 1 and pre.at[cell, "S"] == 0
    s = _rerun(r, events=ev2)
    assert cell not in s.index or not s.at[cell, "bh_flag"]


def test_planted_drop_without_a_calm_followup_is_unobserved_not_negative(runs):
    """Remove every calm small-boat pass around one planted slowdown (rough weather): it must count as
    followup_unobserved and say so, never as a clean negative (L = 0)."""
    from fuse import reasons
    from fuse.link import _link_slowdowns, sites

    r = runs[SEEN[0]]
    f = r["frames"]
    ev, obs, cells = f["match/events"], f["aggregate/observed"].copy(), f["fuse/cells"].copy()
    site = r["site"]
    slow = ev[(ev["event_type"] == "slowdown") & (ev["cell_id"] == site)].sort_values("time_utc")
    day = pd.Timestamp(slow["time_utc"].iloc[-1].tz_convert("UTC").date())
    from core.grid import neighbours

    fine = sorted(obs.loc[obs["level"] == FINE, "cell_id"].unique())
    N = {site, *neighbours(fine, PARAMS["link_radius_m"])[site]}
    lo, hi = (
        day - pd.Timedelta(days=PARAMS["link_days"] + 1),
        day + pd.Timedelta(days=PARAMS["link_days"] + 1),
    )

    def storm(frame):
        d = pd.to_datetime(frame["date"])
        return (frame["event_type"] == "dark_small") & frame["cell_id"].isin(N) & d.between(lo, hi)

    m = storm(obs)
    obs.loc[m, ["count", "exposure"]] = 0.0
    cells = cells[~storm(cells)]
    before = sites(_link_slowdowns(f["fuse/cells"], f["aggregate/observed"], ev, r["T"]))
    before = before.set_index("site_id")
    slow_after = _link_slowdowns(cells, obs, ev, r["T"])
    hit = slow_after[(slow_after["cell_id"] == site) & (pd.to_datetime(slow_after["date"]) == day)]
    assert len(hit) and (hit["X"] == 0).all() and hit["L"].isna().all()  # no L, never L = 0
    after = sites(slow_after).set_index("site_id")
    assert after.at[site, "followup_unobserved"] > before.at[site, "followup_unobserved"]
    assert any("unobserved" in x for x in reasons(after.loc[site].to_dict(), {}))


def test_null_test_flags_noise_rarely(runs):
    """P1's null test (#48) on seed 1: time-shuffled runs flag a site in at most about q of them. Few runs here to
    keep CI fast; the PR reports a longer run with its Wilson interval."""
    from validate.null import null_test

    r = runs[SEEN[0]]
    mp = pytest.MonkeyPatch()
    for n, f in r["frames"].items():
        mp.setattr(io, "read_stage", lambda name, _f=r["frames"]: _f[name])
    mp.setattr(io, "read_snapshot", lambda: {"T": r["T"]})
    try:
        out = null_test(runs=5, seed=0)
    finally:
        mp.undo()
    assert out["runs"] == 5 and out["share_with_any_flag"] <= 2 * PARAMS["fdr_q"]
    assert 0 <= out["lo"] <= out["share_with_any_flag"] <= out["hi"] <= 1


def test_one_fuse_run_fits_the_a13_budget(runs):
    assert max(r["secs"] for r in runs.values()) < 30  # A13: over 30 s means fewer null runs
