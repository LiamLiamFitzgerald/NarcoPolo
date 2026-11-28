"""P4 match parameters and the grid: docs/specs/P4.md Parameters, overlaid by config.yaml's `p4` block.
Kept apart from detect/_common.py on purpose: tach lets match/ import only core."""

from typing import Any

import numpy as np

from core import io
from core.config import load
from core.grid import FINE, cell_index
from core.grid import cell_id as _cell_id

# TODO(P1): add a `p4:` block to config.yaml with these keys (#183); until then the spec values below apply.
_SPEC: dict[str, Any] = {
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
}
CFG: dict[str, Any] = {**_SPEC, **dict(load(io.CONFIG_PATH)[0].get("p4", {}))}

KN_TO_MS = 0.514444
RAW_ID_COLUMNS = {"ship_id", "mmsi", "imo", "call_sign", "callsign", "name", "vessel_name", "ssvid"}


def cell_ids(x_m, y_m) -> np.ndarray:
    """2 km cell id (core.grid, the format every stage file uses) of each position in EPSG:32629."""
    ix, iy = cell_index(x_m, y_m, FINE)
    return np.array(
        [_cell_id(int(a), int(b), FINE) for a, b in zip(ix, iy, strict=True)], dtype=object
    )
