"""Matching to GFW SAR, dark_small events, slowdowns, ship_key, events.parquet."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize

from match._standin import CFG, EVENTS_COLUMNS, check_events

log = logging.getLogger(__name__)


def match(dets: pd.DataFrame, gfw_sar: pd.DataFrame, gate_m: float = CFG["match_gate_m"]) -> np.ndarray:
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
            d["x_m"].to_numpy()[:, None] - g["x_m"].to_numpy(), d["y_m"].to_numpy()[:, None] - g["y_m"].to_numpy()
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
        log.info("large detections matched to GFW: %.2f of %d", dets.loc[large, "matched"].mean(), large.sum())
    d = dets[dets["size_class"].isin(["small", "medium"]) & ~dets["matched"].astype(bool)]
    return pd.DataFrame({
        "event_id": "dark_small-" + d["det_id"].astype(str), "event_type": "dark_small", "time_utc": d["time_utc"],
        "x_m": d["x_m"], "y_m": d["y_m"], "cell_id": d["cell_id"], "p": d["p_boat"].astype(float),
        "duration_min": np.nan, "ship_key": None, "matched": False,
    }).reset_index(drop=True)  # fmt: skip


def slowdowns_from_presence(presence2km, cells, era5) -> pd.DataFrame:  # stub, issue #9
    return pd.DataFrame(columns=EVENTS_COLUMNS)


def slowdowns_from_tracks(ais) -> pd.DataFrame:  # stub, issue #9
    return pd.DataFrame(columns=EVENTS_COLUMNS)


def ship_key(ship_id) -> str:  # stub, issue #10
    return ""


def write_events(*frames, out: Path = Path("match/events.parquet")) -> Path:  # stub, issue #10
    df = pd.concat(frames) if frames else pd.DataFrame(columns=EVENTS_COLUMNS)
    df = df.astype({"p": float, "matched": bool})
    df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
    check_events(df).to_parquet(out)
    return out
