"""Issue 59: pier scores, reasons, fuse/sites + fuse/piers + fuse/links (simulator first)."""

import json
import re
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from core import io
from core.config import load
from fuse import pier_scores, reasons
from fuse.link import _NO_PIER, _finish
from sim.simulate import simulate

_SITE = {
    "site_id": "a", "x_m": 0.0, "y_m": 0.0, "n_slowdowns": 3, "S": 1.0, "p_perm": 0.001, "bh_flag": True,
    "recurrence": 2, "followup_unobserved": 1, "agreement": 3, "reasons": [], "top_piers": [],
}  # fmt: skip


def _sites(*rows):
    return pd.DataFrame([_SITE | r for r in rows])


def test_pier_nearer_by_sea_beats_pier_nearer_in_a_straight_line():
    """Headland: pier 'across' is close as the crow flies but 3 h by sea; 'round' is 0.5 h by sea."""
    travel = pd.DataFrame(
        {"cell_id": ["a", "a"], "pier_id": ["across", "round"], "hours": [3.0, 0.5]}
    )
    P, top = pier_scores(_sites({}), travel)
    assert top["a"] == ["round", "across"] and P["round"] > P["across"]
    assert P["round"] == pytest.approx(np.exp(-0.5))


def test_no_flagged_sites_falls_back_to_top5_unflagged():
    s = _sites(*({"site_id": f"s{i}", "S": float(i), "bh_flag": False} for i in range(8)))
    travel = pd.DataFrame({"cell_id": [f"s{i}" for i in range(8)], "pier_id": "p", "hours": 1.0})
    _, top = pier_scores(s, travel)
    assert sorted(top) == ["s3", "s4", "s5", "s6", "s7"]
    out, *_ = _finish(s, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, None, travel, None)
    assert all(
        any(r.startswith(("Not flagged", "Not tested")) for r in rs) for rs in out["reasons"]
    )


def test_flagged_site_without_reachable_pier_says_so():
    travel = pd.DataFrame({"cell_id": ["elsewhere"], "pier_id": ["p"], "hours": [1.0]})
    out, piers, _ = _finish(
        _sites({}), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, None, travel, None
    )
    assert out.at[0, "top_piers"] == [] and any(_NO_PIER in r.lower() for r in out.at[0, "reasons"])
    assert piers["P_j"].tolist() == [0.0]  # every road-access pier gets a row


def test_road_access_only():
    travel = pd.DataFrame(
        {"cell_id": ["a", "a"], "pier_id": ["road", "track"], "hours": [2.0, 0.1]}
    )
    piers = pd.DataFrame({"pier_id": ["road", "track"], "road_access": [True, False]})
    out, P, _ = _finish(
        _sites({}), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, None, travel, piers
    )
    assert out.at[0, "top_piers"] == ["road"] and P["pier_id"].tolist() == ["road"]


def test_reasons_mention_unobserved_followup_and_follow_language_rule():
    st = pd.Series({"lag_days": 2, "agreement": 3})
    r = reasons(_SITE, {"strongest": st, "C": 1.8, "mu": 0.1, "dist_coast_m": 14000.0, "lane": False,
                        "inshore_frac": 0.0, "significant": True, "n_tested": 40})  # fmt: skip
    text = " ".join(r).lower()
    assert "follow-up unobserved" in text and "1.8" in text and "0.1" in text and "14 km" in text
    assert "smuggling" not in text and "detected" not in text.replace("detection", "")
    assert "angles" in text and "%" not in text  # agreement as angles, never a probability


@pytest.fixture(scope="module")
def sim_out(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("p6piers")
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    cfg = tmp / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    mp.setattr(io, "CONFIG_PATH", cfg)
    simulate(load(cfg)[0], 20261127)
    import fuse

    fuse.run()
    out = {
        n: io.read_stage(n)
        for n in ("fuse/sites", "fuse/piers", "fuse/links", "reference/travel_hours")
    }
    yield tmp, out
    mp.undo()


def test_sim_outputs_are_consistent(sim_out):
    _, o = sim_out
    s, links = o["fuse/sites"], o["fuse/links"]
    assert s["reasons"].map(len).gt(0).all()
    assert set(links["site_id"]) <= set(s["site_id"])
    S = links.assign(w=links["L"] * 0.5 ** (links["age_days"] / 30)).groupby("site_id")["w"].sum()
    assert np.allclose(S.to_numpy(), s.set_index("site_id").loc[S.index, "S"].to_numpy())
    has_unobs = s[s["followup_unobserved"] > 0]
    assert has_unobs["reasons"].map(lambda r: any("unobserved" in x for x in r)).all()


def test_sim_top_piers_follow_sea_travel_time(sim_out):
    _, o = sim_out
    t = o["reference/travel_hours"].set_index(["cell_id", "pier_id"])["hours"]
    for _, site in o["fuse/sites"].iterrows():
        h = [t[(site["site_id"], p)] for p in site["top_piers"]]
        assert h == sorted(h)


def test_no_identity_or_verdict_in_outputs(sim_out, tmp_path):
    _, o = sim_out
    dump = tmp_path / "out"
    dump.mkdir()
    for n, f in o.items():
        (dump / f"{n.replace('/', '_')}.json").write_text(
            f.to_json(orient="records", date_format="iso")
        )
    text = " ".join(" ".join(r) for r in o["fuse/sites"]["reasons"]).lower()
    assert "smuggling" not in text and "ship_key" not in json.dumps(list(o["fuse/sites"].columns))
    res = subprocess.run(
        [sys.executable, str(io.ROOT / "scripts" / "scan_identities.py"), str(dump)], check=False
    )
    assert res.returncode == 0


@pytest.mark.slow
def test_pure_run_is_deterministic_and_touches_no_files(sim_out):
    from fuse.link import _run

    tmp, _ = sim_out
    names = [
        "aggregate/observed",
        "forecast/expected",
        "reference/cells",
        "reference/travel_hours",
        "match/events",
    ]
    mp = pytest.MonkeyPatch()
    mp.setenv("NARCO_DATA", str(tmp / "data"))
    frames = [io.read_stage(n) for n in names]
    cells = io.read_stage("fuse/cells")
    before = {p: p.stat().st_mtime_ns for p in (tmp / "data").rglob("*") if p.is_file()}
    a = _run(*frames, cells=cells)[1]
    b = _run(*frames, cells=cells)[1]
    after = {p: p.stat().st_mtime_ns for p in (tmp / "data").rglob("*") if p.is_file()}
    mp.undo()
    pd.testing.assert_frame_equal(a, b)
    assert before == after
    assert not any(re.search(r"smuggl", " ".join(r), re.IGNORECASE) for r in a["reasons"])


def test_reasons_quote_the_live_forecast_mu_only():
    """#198: the expected count in a reason comes from fold == 0; a backtest or no-fold row for the same cell-day
    must not be quoted instead."""
    day = pd.Timestamp("2026-11-01")
    obs = pd.DataFrame(
        {"cell_id": ["b"], "level": [2000], "date": [day], "event_type": ["dark_small"], "count": [1.8],
         "exposure": [1.0]}
    )  # fmt: skip
    exp = pd.DataFrame(
        {"cell_id": ["b"] * 3, "date": [day] * 3, "event_type": ["dark_small"] * 3, "mu": [5.0, 7.0, 0.1],
         "fold": pd.array([None, 1, 0], dtype="Int64")}
    )  # fmt: skip
    strongest = pd.DataFrame(
        {
            "agreement": [2],
            "small_cell": ["b"],
            "small_date": [day],
            "lag_days": [1],
            "event_id": ["e"],
        },
        index=["a"],
    )
    out, *_ = _finish(_sites({}), pd.DataFrame(), strongest, obs, exp, None, None, None)
    text = " ".join(out.at[0, "reasons"])
    assert "where 0.1 were expected" in text
