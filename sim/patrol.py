"""Simulated patrol outcomes (docs/learning.md L1): what a visit to a site would have found, from the truth file.

Only visited sites get a row: an unvisited site is unknown, never "found nothing" (learning principle 3).
"""

import zlib

import numpy as np
import pandas as pd

from core import io
from core.config import load

COLUMNS = ["site_id", "asset", "visited", "found"]
WEEK = pd.Timedelta(days=7)


def _utc(t: object) -> pd.Timestamp:
    ts = pd.Timestamp(t)  # pyright: ignore[reportArgumentType]
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def patrol_outcome(truth: pd.DataFrame, plan: dict, week: object) -> pd.DataFrame:
    """One row per site stop in `plan` whose arrival is in [week, week + 7 days).

    found = an active drop at that site within `learn.find_window_h` of the arrival, kept with probability
    `learn.p_find_ship` or `learn.p_find_aircraft` (a visit can miss activity). The draw is seeded by the week, the
    site and the asset, so the same inputs always give the same outcomes. The base stop ("base") is not a site.
    """
    lc = load(io.CONFIG_PATH)[0]["learn"]
    p_find = {"ship": lc["p_find_ship"], "aircraft": lc["p_find_aircraft"]}
    window = pd.Timedelta(hours=float(lc["find_window_h"]))
    start = _utc(week)
    drops = truth[(truth["kind"] == "drop") & truth["active"].astype(bool)]
    drop_t = pd.to_datetime(drops["time_utc"], utc=True)
    rows = []
    for asset, stops in plan.items():
        for stop in stops:
            sid, at = stop["id"], _utc(stop["arrival_utc"])
            if sid == "base" or not start <= at < start + WEEK:
                continue
            near = ((drops["site_id"] == sid) & ((drop_t - at).abs() <= window)).any()
            key = [int(start.value // 86_400_000_000_000), zlib.crc32(f"{sid}|{asset}".encode())]
            hit = np.random.default_rng(key).random() < p_find[asset]
            rows.append((sid, asset, True, bool(near and hit)))
    return pd.DataFrame(rows, columns=COLUMNS).astype({"visited": bool, "found": bool})
