"""Issue 320: the briefing card's evidence checks and travel hours, known answers on hand-built frames."""

import math

import pandas as pd
import pandera.pandas as pa
import pytest

from core import schemas
from fuse import link
from fuse._common import PARAMS
from fuse.link import _EVIDENCE, _declared, _evidence, _finish, _rare_slowdown

_SITE = {
    "site_id": "a", "x_m": 0.0, "y_m": 0.0, "n_slowdowns": 1, "S": 1.0, "p_perm": 0.5, "bh_flag": True,
    "recurrence": 0, "followup_unobserved": 0, "agreement": 0, "reasons": [], "top_piers": [],
}  # fmt: skip
DAY = pd.Timestamp("2026-11-01")


def _sites(*ids):
    return pd.DataFrame([_SITE | {"site_id": i} for i in ids])


def test_rare_slowdown_is_the_top_frac_of_slowdown_mid_p_ranks():
    """20 slowdown cell-days with p_mid 0.01 .. 0.20: top 10% (rank > 0.9) is exactly the two smallest p. The
    dark_small rows (even smaller p) are ranked in their own type and change nothing; an unscored cell is False."""
    assert PARAMS["top_frac"] == 0.1
    slow = pd.DataFrame(
        {"cell_id": [f"c{i}" for i in range(20)], "date": DAY, "event_type": "slowdown",
         "p_mid": [(i + 1) / 100 for i in range(20)]}
    )  # fmt: skip
    small = slow.assign(event_type="dark_small", p_mid=1e-6)
    cells = pd.concat([slow, small], ignore_index=True)
    got = _rare_slowdown(
        cells, ["c0", "c1", "c2", "c0", "nowhere"], [DAY, DAY, DAY, DAY + pd.Timedelta(days=1), DAY]
    )
    assert got.tolist() == [True, True, False, False, False]


def test_evidence_checks_per_site():
    """a: linked slowdown seen (L > 0), rare, outside fishing. b: L = 0 and no L, inside fishing. c: no inshore
    map, so outside_fishing is NA (unknown is never yes)."""
    slow = pd.DataFrame(
        {"cell_id": ["a", "b", "b", "c"], "L": [0.3, 0.0, float("nan"), float("nan")]}
    )
    strongest = pd.DataFrame({"rare_slowdown": [True]}, index=["a"])
    lay = pd.DataFrame(
        {
            "inshore_frac": [0.05, 0.5, float("nan")],
            "lane": False,
            "anchorage": False,
            "port_zone": False,
        },
        index=["a", "b", "c"],
    )
    ev = _evidence(_sites("a", "b", "c"), slow, strongest, lay)
    assert ev["check_rare_slowdown"].tolist() == [True, False, False]
    assert ev["check_followup_seen"].tolist() == [True, False, False]
    assert ev["check_outside_fishing"].tolist() == [True, False, pd.NA]
    no_map = _evidence(_sites("a"), pd.DataFrame(), pd.DataFrame(), None)
    assert no_map["check_outside_fishing"].isna().all() and not no_map["check_followup_seen"].any()


def test_top_piers_hours_follow_top_piers_and_checks_give_reasons():
    travel = pd.DataFrame(
        {
            "cell_id": ["a", "a", "a", "z"],
            "pier_id": ["p3", "p1", "p2", "p1"],
            "hours": [3.0, 0.5, 1.5, 0.1],
        }
    )
    s = _sites("a", "b")
    slow = pd.DataFrame({"cell_id": ["a"], "L": [0.4], "age_days": [3.0]})
    strongest = pd.DataFrame(
        {"agreement": [2], "small_cell": ["a"], "small_date": [DAY], "lag_days": [1], "event_id": ["e"],
         "slow_date": [DAY], "rare_slowdown": [True]},
        index=["a"],
    )  # fmt: skip
    layers = pd.DataFrame(
        {"cell_id": ["a", "b"], "inshore_frac": [0.0, float("nan")], "lane": False, "anchorage": False,
         "port_zone": False}
    )  # fmt: skip
    out, *_ = _finish(s, slow, strongest, pd.DataFrame(), None, layers, travel, None)
    a, b = out.iloc[0], out.iloc[1]
    assert a["top_piers"] == ["p1", "p2", "p3"] and a["top_piers_hours"] == [0.5, 1.5, 3.0]
    assert b["top_piers"] == [] and b["top_piers_hours"] == []
    ra, rb = " ".join(a["reasons"]), " ".join(b["reasons"])
    assert (
        "Rare slowdown: yes" in ra
        and "Small boat seen after: yes" in ra
        and "Outside fishing grounds: yes" in ra
    )
    assert (
        "Rare slowdown: no" in rb
        and "Small boat seen after: no" in rb
        and "Outside fishing grounds: unknown" in rb
    )
    text = (ra + rb).lower()
    assert "smuggling" not in text and "%" not in text


def test_evidence_columns_are_written_only_once_the_schema_declares_them(monkeypatch):
    """Until P1's #320 schema PR the strict fuse/sites schema has no evidence columns: they are dropped and the
    frame stays valid. Once declared, each one is kept."""
    travel = pd.DataFrame({"cell_id": ["a"], "pier_id": ["p1"], "hours": [0.5]})
    out, *_ = _finish(
        _sites("a"), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), None, None, travel, None
    )
    assert set(_EVIDENCE) <= set(out.columns)
    today = _declared(out)
    if not set(_EVIDENCE) & set(schemas.SCHEMAS["fuse/sites"].columns):
        assert not set(_EVIDENCE) & set(today.columns)
    schemas.check("fuse/sites", today)
    wider = schemas.SCHEMAS["fuse/sites"].add_columns(
        {"check_rare_slowdown": pa.Column(bool), "top_piers_hours": pa.Column(object)}
    )
    monkeypatch.setitem(link.SCHEMAS, "fuse/sites", wider)
    kept = _declared(out)
    assert {"check_rare_slowdown", "top_piers_hours"} <= set(kept.columns)
    assert "check_followup_seen" not in kept.columns or "check_followup_seen" in wider.columns


@pytest.mark.parametrize("frac", [float("nan"), 0.09, 0.1])
def test_outside_fishing_uses_the_dark_small_threshold(frac):
    """inshore_frac < inshore_max (0.1, the dark_small context rule): 0.09 yes, 0.1 no, NaN unknown."""
    lay = pd.DataFrame({"inshore_frac": [frac]}, index=["a"])
    v = _evidence(_sites("a"), pd.DataFrame(), pd.DataFrame(), lay)["check_outside_fishing"].iloc[0]
    assert (v is pd.NA) if math.isnan(frac) else (bool(v) == (frac < PARAMS["inshore_max"]))


@pytest.mark.parametrize("flag", ["lane", "anchorage", "port_zone"])
def test_rare_slowdown_is_never_true_where_ships_stop_routinely(flag):
    """#320 follow-up: an anchorage with ~150 slowdowns always has one in the top 10%, so a lane, anchorage or
    port-zone cell is never a rare slowdown; unknown layers are not "yes" either."""
    strongest = pd.DataFrame({"rare_slowdown": [True, True]}, index=["a", "b"])
    lay = pd.DataFrame(
        {"inshore_frac": [0.0, 0.0], "lane": False, "anchorage": False, "port_zone": False},
        index=["a", "b"],
    )
    lay.loc["b", flag] = True
    ev = _evidence(_sites("a", "b"), pd.DataFrame(), strongest, lay)
    assert ev["check_rare_slowdown"].tolist() == [True, False]
    no_layers = _evidence(_sites("a"), pd.DataFrame(), strongest.loc[["a"]], lay[["inshore_frac"]])
    assert not no_layers["check_rare_slowdown"].iloc[0]
