"""Patrol outcomes on the simulator (docs/learning.md L1): did a planned visit find a planted drop?"""

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from core.config import load
from core.io import CONFIG_PATH

COLUMNS = ["site_id", "asset", "visited", "found"]


def patrol_outcome(truth: pd.DataFrame, plan: Mapping[str, Any], week: int) -> pd.DataFrame:
    """One row per planned stop. found: an active drop at that site within learn.find_window_h of the arrival,
    thinned by the asset's p_find. Sites not in the plan get no row: unvisited is not "found nothing"."""
    cfg, _ = load(CONFIG_PATH)
    learn = cfg["learn"]
    window = pd.Timedelta(hours=learn["find_window_h"])
    drops = truth[truth["active"].fillna(False).astype(bool)]
    rng = np.random.default_rng([cfg["seed"], int(week)])
    rows = []
    for asset, stops in plan.items():
        p_find = learn[f"p_find_{asset}"]
        for stop in stops:
            at = pd.Timestamp(stop["arrival_utc"])
            here = drops[drops["site_id"] == stop["id"]]
            near = bool(((pd.to_datetime(here["time_utc"], utc=True) - at).abs() <= window).any())
            rows.append((stop["id"], asset, True, near and bool(rng.random() < p_find)))
    return pd.DataFrame(rows, columns=COLUMNS)
