"""Matching to GFW SAR, dark_small events, slowdowns, ship_key, events.parquet."""

from pathlib import Path

import numpy as np
import pandas as pd

from match._standin import EVENTS_COLUMNS, check_events


def match(dets, gfw_sar, gate_m=500) -> np.ndarray:  # stub, issue #8
    return np.zeros(len(dets), bool)


def dark_small_events(dets) -> pd.DataFrame:  # stub, issue #8
    return pd.DataFrame(columns=EVENTS_COLUMNS)


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
