"""Matching to GFW SAR, dark_small events, slowdowns, ship_key, events.parquet."""

import hashlib
import logging
import os
from typing import Literal

import numpy as np
import pandas as pd
from scipy import optimize

from core import io
from core.schemas import SCHEMAS
from match._common import CFG, KN_TO_MS, RAW_ID_COLUMNS, cell_ids

EVENTS_COLUMNS = list(SCHEMAS["match/events"].columns)

log = logging.getLogger(__name__)


def match(
    dets: pd.DataFrame, gfw_sar: pd.DataFrame, gate_m: float = CFG["match_gate_m"]
) -> np.ndarray:
    """One-to-one match of each pass's detections to GFW SAR detections with matched = True (issue 1).

    A GFW row belongs to the pass if its time is within ais_window_min of the pass time.
    Pairs beyond gate_m cost match_big_cost and are dropped after assignment.
    TODO(P2): assumes raw/gfw_sar.parquet carries x_m, y_m (EPSG:32629), time_utc and matched.
    """
    out = np.zeros(len(dets), bool)
    ais = gfw_sar[gfw_sar["matched"].astype(bool)]
    window = pd.Timedelta(minutes=CFG["ais_window_min"])
    for idx in dets.groupby("pass_id").indices.values():
        d = dets.iloc[idx]
        g = ais[(ais["time_utc"] - d["time_utc"].iloc[0]).abs() <= window]
        if g.empty:
            continue
        dist = np.hypot(
            d["x_m"].to_numpy()[:, None] - g["x_m"].to_numpy(),
            d["y_m"].to_numpy()[:, None] - g["y_m"].to_numpy(),
        )
        r, c = optimize.linear_sum_assignment(np.where(dist <= gate_m, dist, CFG["match_big_cost"]))
        out[idx[r[dist[r, c] <= gate_m]]] = True
    return out


def dark_small_events(dets: pd.DataFrame) -> pd.DataFrame:
    """Unmatched small and medium detections -> dark_small events with p = p_boat.

    dets needs the matched column from match(). Logs the share of large detections that matched:
    a sudden drop signals a matching bug, and areas where most large ships are unmatched have poor AIS.
    """
    large = dets["size_class"] == "large"
    if large.any():
        log.info(
            "large detections matched to GFW: %.2f of %d",
            dets.loc[large, "matched"].mean(),
            large.sum(),
        )
    d = dets[dets["size_class"].isin(["small", "medium"]) & ~dets["matched"].astype(bool)]
    return pd.DataFrame({
        "event_id": "dark_small-" + d["det_id"].astype(str), "event_type": "dark_small", "time_utc": d["time_utc"],
        "x_m": d["x_m"], "y_m": d["y_m"], "cell_id": d["cell_id"], "p": d["p_boat"].astype(float),
        "duration_min": np.nan, "ship_key": None, "matched": False,
    }).reset_index(drop=True)  # fmt: skip


def _dark_medium_events(dets: pd.DataFrame) -> pd.DataFrame:
    """Unmatched medium detections -> dark_medium events (#344), for the fisheries lens.

    The same rows also stay in dark_small (spec: dark_small covers small and medium; DECISIONS.md #344), so each
    event type is a complete count on its own. Same columns and rules as dark_small, calm passes only.
    """
    ev = dark_small_events(dets[dets["size_class"] == "medium"])
    return ev.assign(
        event_type="dark_medium",
        event_id=ev["event_id"].str.replace("dark_small-", "dark_medium-", n=1, regex=False),
    )


def _outside_exclusion_and_calm(
    ev: pd.DataFrame, cells: pd.DataFrame, weather: pd.DataFrame
) -> pd.DataFrame:
    """Keep events in known, non-exclusion cells whose daily max wave height is below storm_hs_m.

    weather: coverage/weather_daily (cell_id, date, hs_max_m). Cell-days with no wave data are dropped:
    without it a weather stop can't be ruled out.
    """
    hs = weather.assign(date=pd.to_datetime(weather["date"]))
    hs = hs.groupby(["cell_id", "date"], as_index=False)["hs_max_m"].max()
    ev = ev.assign(date=pd.to_datetime(ev["date"]))
    ev = ev.merge(cells.loc[~cells["exclusion"].astype(bool), ["cell_id"]], on="cell_id")
    ev = ev.merge(hs, on=["cell_id", "date"])
    return ev[ev["hs_max_m"] < CFG["storm_hs_m"]]


def _events(ev: pd.DataFrame) -> pd.DataFrame:
    return ev.assign(event_type="slowdown", p=1.0, matched=False)[EVENTS_COLUMNS].reset_index(
        drop=True
    )


def slowdowns_from_presence(
    presence2km: pd.DataFrame, cells: pd.DataFrame, era5: pd.DataFrame
) -> pd.DataFrame:
    """One slowdown per cell-day with slow cargo presence-hours (issue 3; #239), outside exclusion, calm sea.

    presence2km: reference/presence_2km (cell_id, date, vessel_type, speed_bin, hours); kept are
    presence_vessel_types in the presence_slow_bins. cells: cell_id, exclusion, x_m, y_m (centre).
    era5: coverage/weather_daily (cell_id, date, hs_max_m).
    time = slowdown_hour_utc on the date; duration_min = hours x 60 (#131); no ship_key.
    """
    slow = presence2km[presence2km["vessel_type"].isin(CFG["presence_vessel_types"])
                       & presence2km["speed_bin"].isin(CFG["presence_slow_bins"])]  # fmt: skip
    ev = slow.groupby(["cell_id", "date"], as_index=False)["hours"].sum()
    ev = _outside_exclusion_and_calm(ev[ev["hours"] > 0], cells, era5)
    ev = ev.merge(cells[["cell_id", "x_m", "y_m"]], on="cell_id")
    ev["time_utc"] = pd.to_datetime(ev["date"]).dt.tz_localize("UTC") + pd.Timedelta(
        hours=CFG["slowdown_hour_utc"]
    )
    ev["event_id"] = (
        "slowdown-"
        + ev["cell_id"].astype(str)
        + "-"
        + pd.to_datetime(ev["date"]).dt.strftime("%Y%m%d")
    )
    return _events(ev.assign(duration_min=ev["hours"] * 60, ship_key=None))


def _ship_slowdowns(t: pd.DataFrame) -> list[dict]:
    """Per-ship rule on one ship's pings (sorted): cruise >= cruise_kn in the previous hour, then
    a rolling median < slow_kn for >= slow_min, with enough pings and no gap > ais_window_min."""
    gap = pd.Timedelta(minutes=CFG["ais_window_min"])
    med = (
        t.rolling(f"{CFG['rolling_median_min']}min", on="time_utc")["speed_ms"].median().to_numpy()
    )
    slow = med < CFG["slow_kn"] * KN_TO_MS
    seg = np.cumsum(
        ~slow | (t["time_utc"].diff() > gap).to_numpy()
    )  # new id at every fast ping or long gap
    out = []
    for s_id in np.unique(seg[slow]):
        g = t[(seg == s_id) & slow]
        start, end = g["time_utc"].iloc[0], g["time_utc"].iloc[-1]
        prev = t[(t["time_utc"] >= start - pd.Timedelta(hours=1)) & (t["time_utc"] < start)]
        if (
            len(g) >= CFG["min_pings_slow"]
            and end - start >= pd.Timedelta(minutes=CFG["slow_min"])
            and len(prev) >= CFG["min_pings_cruise_hour"]
            and prev["speed_ms"].median() >= CFG["cruise_kn"] * KN_TO_MS
        ):
            out.append({"time_utc": start, "x_m": g["x_m"].median(), "y_m": g["y_m"].median(),
                        "duration_min": (end - start).total_seconds() / 60})  # fmt: skip
    return out


def slowdowns_from_tracks(
    ais: pd.DataFrame, *, cells: pd.DataFrame, era5: pd.DataFrame
) -> pd.DataFrame:
    """Per-ship slowdowns, only if a track source turns up. Never interpolates a slowdown into existence.

    era5: coverage/weather_daily, as for slowdowns_from_presence.
    TODO(P2): assumed ais columns: ship_id, time_utc, x_m, y_m, sog_kn, ship_type. Raw ids are
    hashed to ship_key here and never leave this function.
    """
    types = np.zeros(len(ais), bool)
    for lo, hi in CFG["ship_types"]:
        types |= ais["ship_type"].between(lo, hi).to_numpy()
    a = ais[types].assign(speed_ms=ais["sog_kn"] * KN_TO_MS).sort_values(["ship_id", "time_utc"])
    rows = [
        r | {"ship_key": ship_key(sid)}
        for sid, t in a.groupby("ship_id")
        for r in _ship_slowdowns(t.reset_index())
    ]
    ev = pd.DataFrame(rows, columns=["time_utc", "x_m", "y_m", "duration_min", "ship_key"])
    ev["cell_id"] = cell_ids(ev["x_m"], ev["y_m"]) if len(ev) else []
    ev["date"] = ev["time_utc"].dt.tz_convert(None).dt.normalize() if len(ev) else []
    ev = _outside_exclusion_and_calm(ev, cells, era5)
    ev["event_id"] = [
        "slowdown-" + k[:12] + "-" + t.strftime("%Y%m%dT%H%M")
        for k, t in zip(ev["ship_key"], ev["time_utc"], strict=True)
    ]
    return _events(ev)


def ship_key(ship_id) -> str:
    """Salted SHA-256 of a raw ship id. The salt comes from the environment, never from code or files.

    Unsalted, a hash of a 9-digit MMSI is reversible by brute force, so a missing salt is an error.
    """
    salt = os.environ.get(CFG["ship_key_salt_env"])
    if not salt:
        raise RuntimeError(f"set {CFG['ship_key_salt_env']} before hashing ship ids")
    return hashlib.sha256(f"{salt}:{ship_id}".encode()).hexdigest()


def write_events(
    *frames: pd.DataFrame, provenance: Literal["simulated", "real"] = "real"
) -> pd.DataFrame:
    """Write the dark_small, dark_medium and slowdown frames as the events stage file through core.io (schema check, config
    hash, provenance). Refuses any raw ship identifier column. Returns the frame it wrote."""
    raw = RAW_ID_COLUMNS & {c.lower() for f in frames for c in f.columns}
    if raw:
        raise ValueError(f"raw ship identifiers must never be written: {sorted(raw)}")
    parts = [f for f in frames if len(f)]
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=EVENTS_COLUMNS)
    text = {c: "string[pyarrow]" for c in ("event_id", "event_type", "cell_id", "ship_key")}
    df = df.astype({"p": float, "matched": bool, "duration_min": float, **text})
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    assert df["event_id"].is_unique, "duplicate event_id"
    df = df[EVENTS_COLUMNS]
    io.write_stage("match/events", df, provenance)
    return df
