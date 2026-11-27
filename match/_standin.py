"""TODO(P1): temporary stand-ins for core.config and core.schemas (events). Swap for P1 code.

Duplicated from detect/_standin.py on purpose: tach lets match/ import only core.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

P4_MATCH_DEFAULTS: dict[str, Any] = {
    "ais_window_min": 30,
    "match_gate_m": 500,
    "match_big_cost": 1e9,  # spec: large finite cost, scipy can reject inf
    "presence_slow_kn": 2,  # issue 3 / pseudo-codebase: slowest GFW bin, < 2 kn
    "slow_kn": 3,
    "cruise_kn": 8,
    "slow_min": 20,
    "storm_hs_m": 4,
    "rolling_median_min": 10,
    "min_pings_cruise_hour": 3,
    "min_pings_slow": 2,
    "slowdown_hour_utc": 12,
    "ship_types": [[70, 79], [80, 89]],  # cargo, tankers
    # TODO(P4): env var name for the ship_key salt is not in the spec. Question issue to open.
    "ship_key_salt_env": "NARCO_SHIP_KEY_SALT",
    "cell_m": 2000,
    "x0": None,  # TODO(P1): global grid origin from config
    "y0": None,
}

KN_TO_MS = 0.514444


def load_config(path: Path = Path("config.yaml")) -> dict[str, Any]:
    cfg = dict(P4_MATCH_DEFAULTS)
    if path.exists():
        import yaml

        cfg.update(yaml.safe_load(path.read_text()) or {})
    return cfg


CFG = load_config()

EVENTS_COLUMNS = [
    "event_id", "event_type", "time_utc", "x_m", "y_m", "cell_id", "p", "duration_min", "ship_key", "matched",
]  # fmt: skip
RAW_ID_COLUMNS = {"ship_id", "mmsi", "imo", "call_sign", "callsign", "name", "vessel_name", "ssvid"}


def check_events(df: pd.DataFrame) -> pd.DataFrame:
    """TODO(P1): replace with core.schemas."""
    missing = set(EVENTS_COLUMNS) - set(df.columns)
    assert not missing, f"events missing {missing}"
    assert df["event_type"].isin(["dark_small", "slowdown"]).all()
    assert df["p"].between(0, 1).all(), "p outside [0, 1]"
    assert len(df) == 0 or str(df["time_utc"].dt.tz) == "UTC", "time_utc must be tz-aware UTC"
    return df[EVENTS_COLUMNS]
