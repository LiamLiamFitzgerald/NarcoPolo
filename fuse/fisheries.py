"""Fisheries lens (#321): weekly unmatched medium-size boat activity above normal per 2 km cell, fisheries
candidates and likely landing harbours -> fuse/fisheries (columns as in #346).

Built against the interfaces of #344 (P4 `dark_medium` events), #345 (P5 counts and forecast for them), #346 (the
fuse/fisheries schema) and #322 (closed areas). The radar cannot tell that a boat is fishing; the names say
"medium-size" for that reason.
"""

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from core.grid import FINE
from detectors.scores import (
    tail_pmid,
)  # tach: fuse depends on detectors (#269); one mid-p formula, not two
from fuse._common import PARAMS
from fuse.link import _days, _fmt, _road_travel

COLUMNS = [
    "cell_id", "week", "count", "mu", "y_fish", "y_fish_lo", "y_fish_hi", "p_mid", "flag", "in_closed_area",
    "reasons", "top_harbours", "top_harbours_hours", "lens",
]  # fmt: skip
_KEY = ["cell_id", "date"]


def _medium(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["event_type"] == "dark_medium"].assign(date=lambda f: _days(f["date"]))


def _weekly(observed: pd.DataFrame, expected: pd.DataFrame) -> pd.DataFrame:
    """Every observed cell-week of dark_medium with its live forecast, scored and BH-flagged once over all of them.

    Rows: fine level, exposure > 0 (unobserved cell-days give no row, never a zero), joined to fold 0 of the forecast
    (a day with no live forecast row cannot be scored and is left out). Per cell and ISO week (the Monday):
    count and mu are sums over those days; y_fish = (count + 0.5) / (mu + 0.5).
    The range divides by the sums of the daily 90% bounds: y_fish_lo = (count + 0.5) / (sum hi90 + 0.5) and
    y_fish_hi = (count + 0.5) / (sum lo90 + 0.5). That is a simple bound, not an exact 90% interval of the weekly
    ratio (summing daily quantiles over-states the width).
    p_mid is the mid-p tail of the weekly count (detectors.scores.tail_pmid) with variance phi x mu: for a
    constant daily phi that is exact for the sum of independent days. If phi varies within a cell-week the largest
    is used, which can only make the tail heavier (p_mid larger, fewer flags)."""
    o = _medium(observed[(observed["level"] == FINE) & (observed["exposure"] > 0)])
    e = expected[expected["fold"] == 0] if "fold" in expected else expected  # live forecast (#198)
    m = o[[*_KEY, "count"]].merge(_medium(e)[[*_KEY, "mu", "phi", "lo90", "hi90"]], on=_KEY)
    m["week"] = (m["date"] - pd.to_timedelta(m["date"].dt.day_of_week, unit="D")).dt.date
    w = (
        m.groupby(["cell_id", "week"], sort=True)
        .agg(
            count=("count", "sum"),
            mu=("mu", "sum"),
            lo=("lo90", "sum"),
            hi=("hi90", "sum"),
            phi=("phi", "max"),
        )
        .reset_index()
    )
    top = w["count"] + 0.5
    w["y_fish"] = top / (w["mu"] + 0.5)
    w["y_fish_lo"] = top / (w["hi"] + 0.5)
    w["y_fish_hi"] = top / (w["lo"] + 0.5)
    w["p_mid"] = tail_pmid(w["count"], w["mu"], w["phi"]) if len(w) else np.zeros(0)
    w["flag"] = (
        multipletests(w["p_mid"], alpha=PARAMS["fdr_q"], method="fdr_bh")[0]
        if len(w)
        else np.zeros(0, bool)
    )
    return w.drop(columns=["lo", "hi", "phi"])


def _reasons(c, closed, n_tested: int, has_harbour: bool) -> list[str]:
    """Plain words from the candidate's numbers. Language rule: "unusual", "worth checking"; never a verdict and
    never a vessel identity (there is none in these inputs)."""
    out = [
        f"Unmatched medium-size boats this week: {_fmt(c['count'])} where {_fmt(c['mu'])} were expected.",
        (
            f"Unusual for this cell and week (p = {c['p_mid']:.3g}, still unusual after correcting for "
            f"{n_tested} cell-weeks): worth checking."
        ),
    ]
    out.append(
        "Closed areas unknown here."
        if pd.isna(closed)
        else ("Inside a closed area." if closed else "Outside closed areas.")
    )
    if not has_harbour:
        out.append("No road-access harbour within reach by sea.")
    return out


def fisheries(observed, expected, travel=None, piers=None, closed=None) -> pd.DataFrame:
    """fuse/fisheries rows: flagged cell-weeks with y_fish > 1, sorted by p_mid then y_fish (highest first).

    observed / expected: aggregate/observed- and forecast/expected-shaped frames with `dark_medium` rows (#345).
    travel / piers: reference/travel_hours and reference/piers, as for fuse/sites (road-access piers only).
    closed: optional frame with cell_id and a bool `in_closed_area` (#322 has not defined its layer yet); a cell
    it does not list, or no frame at all, gives NA: unknown is never True.
    top_harbours: per candidate the 3 road-access piers with the largest excess x exp(-T / pier_tau_h), excess =
    count - mu > 0 and T = sea-only travel hours (fuse.link's pier weight). For one candidate the excess is a
    constant factor, so this is the 3 nearest by sea (ties by pier_id); top_harbours_hours in the same order."""
    w = _weekly(observed, expected)
    cand = w[w["flag"] & (w["y_fish"] > 1)]
    cand = cand.sort_values(
        ["p_mid", "y_fish", "cell_id", "week"], ascending=[True, False, True, True]
    )
    cand = cand.reset_index(drop=True)
    flags = pd.Series(pd.NA, index=cand.index, dtype="boolean")
    if closed is not None:
        flags = cand["cell_id"].map(closed.set_index("cell_id")["in_closed_area"].astype("boolean"))
        flags = flags.astype("boolean")
    road = _road_travel(travel, piers)
    tau = PARAMS["pier_tau_h"]
    harbours, hours, rs = [], [], []
    for i, c in cand.iterrows():
        t = road[road["cell_id"] == c["cell_id"]]
        t = t.assign(w=(c["count"] - c["mu"]) * np.exp(-t["hours"].astype(float) / tau))
        t = t[t["w"] > 0].sort_values(["w", "pier_id"], ascending=[False, True]).head(3)
        harbours.append(t["pier_id"].astype(str).tolist())
        hours.append(t["hours"].astype(float).tolist())
        rs.append(_reasons(c, flags[i], len(w), len(t) > 0))
    out = cand.assign(
        in_closed_area=flags,
        reasons=rs,
        top_harbours=harbours,
        top_harbours_hours=hours,
        lens="fisheries",
    )
    return out[COLUMNS]


def _gated(observed, expected, travel, piers) -> pd.DataFrame | None:
    """fuse/fisheries for the zero-arg run, or None until it can exist: core/schemas must declare it (#346) and
    observed must hold dark_medium rows (#344, #345). Closed areas: none until #322 defines the layer (NA)."""
    from core.schemas import SCHEMAS

    if "fuse/fisheries" not in SCHEMAS or not (observed["event_type"] == "dark_medium").any():
        return None
    return fisheries(observed, expected, travel, piers)
