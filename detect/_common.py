"""P4 detect parameters and the grid: docs/specs/P4.md Parameters, overlaid by config.yaml's `p4` block."""

from typing import Any

import numpy as np

from core import io
from core.config import load
from core.grid import FINE, cell_index
from core.grid import cell_id as _cell_id

# TODO(P1): add a `p4:` block to config.yaml with these keys (#183); until then the spec values below apply.
_SPEC: dict[str, Any] = {
    "pixel_m": 10,  # shared.md: 10 m pixels on the fixed region grid (issue 5)
    "land_buffer_m": 300,
    "cfar_outer": 41,
    "cfar_guard": 11,
    # #341 fixed-target suppression: divide each real pass by the median of this many earlier passes of the same
    # relative orbit before CFAR. None = off: the ratio image's tail is heavier than the gamma tail alpha() assumes
    # (P1's simulator: open-sea false alarms ~0 -> 1.02 per km2 per pass), so it needs its own threshold first.
    # TODO(P1): config key.
    "fixed_target_history": None,
    "p_fa": 1e-7,  # then calibrated on injection and null tests
    "enl": 4.4,  # spec: estimate_enl default, also the simulator's L (issue 8)
    "cluster_px": [1, 200],
    "size_small_max_px": 4,
    "size_medium_max_px": 20,
    "pol_agree_m": 30,
    "radar_wavelength_m": 0.0555,
    "ghost_db": 20,
    "ghost_tol_m": 200,
    "ghost_band_m": [4000, 8000],  # used when PRF is missing (issue 6)
    # TODO(P4): Sentinel-1 heading per orbit direction is not in the spec (issue 6). Question issue to open.
    "heading_ascending_deg": None,
    "heading_descending_deg": None,
    "ais_window_min": 30,
    "match_gate_m": 500,
}
CFG: dict[str, Any] = {**_SPEC, **dict(load(io.CONFIG_PATH)[0].get("p4", {}))}


def cell_ids(x_m, y_m) -> np.ndarray:
    """2 km cell id (core.grid, the format every stage file uses) of each position in EPSG:32629."""
    ix, iy = cell_index(x_m, y_m, FINE)
    return np.array(
        [_cell_id(int(a), int(b), FINE) for a, b in zip(ix, iy, strict=True)], dtype=object
    )
