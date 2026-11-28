"""What the simulator knows after it has drawn the world. Passed to the raw-file writers (sim/scenes.py, sim/raw.py),
which only read it. Fields are added at the end, never renamed, so the three writers can be built in parallel."""

from dataclasses import dataclass
from datetime import date

import pandas as pd

from core.config import Config


@dataclass(frozen=True)
class SimWorld:
    config: Config
    seed: int
    start: date  # day 0
    days: int
    fine: pd.DataFrame  # one row per 2 km cell: cell_id, ix, iy, x/y via core.grid, inshore_frac, lane, anchorage, port_zone, sea_frac, ...
    weather: pd.DataFrame  # one row per day: wind_ms, hs_m, rough
    passes: pd.DataFrame  # pass_id, day, time_utc, a, b (footprint in cell units east-west; the whole band north-south)
    boats: pd.DataFrame  # kind, day (fractional), x_m, y_m, length_m, detected, pass (index into passes, -1 if not in a footprint)
    ships: pd.DataFrame  # day (fractional; negative before day 0, back to history_start), x_m, y_m, planted, duration_min
    detections: pd.DataFrame  # the detect/detections stage file
    history_start: int = 0  # first ship-history day (<= 0): days - ship_history_days (#273)
