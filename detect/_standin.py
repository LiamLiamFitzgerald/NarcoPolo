"""TODO(P1): temporary stand-ins for core.config, core.Split, core.schemas, core.io and sim.

Delete this file and import the real P1 code once core/ and sim/ land. Nothing here
is P4 logic; it only lets detect/ run and be tested before P1 merges.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# TODO(P1): replace with core.config. Values are the P4 spec's Parameters section.
P4_DEFAULTS: dict[str, Any] = {
    "pixel_m": 10,  # shared.md: 10 m pixels on the fixed region grid (issue 5)
    "land_buffer_m": 300,
    "cfar_outer": 41,
    "cfar_guard": 11,
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
    "cell_m": 2000,
    "x0": None,  # TODO(P1): global grid origin from config
    "y0": None,
}

KN_TO_MS = 0.514444


def load_config(path: Path = Path("config.yaml")) -> dict[str, Any]:
    """P4 defaults, overlaid by config.yaml if P1 has written one."""
    cfg = dict(P4_DEFAULTS)
    if path.exists():
        import yaml

        cfg.update(yaml.safe_load(path.read_text()) or {})
    return cfg


CFG = load_config()


@dataclass(frozen=True)
class Split:
    """TODO(P1): replace with core.Split. Fit only before train_end; test after the embargo."""

    train_end: datetime
    embargo_days: int = 7

    def train(self, df: pd.DataFrame) -> pd.DataFrame:
        return df[df["time_utc"] < self.train_end]

    def test(self, df: pd.DataFrame) -> pd.DataFrame:
        return df[df["time_utc"] >= self.train_end + timedelta(days=self.embargo_days)]


# TODO(P1): replace with core.schemas (data dictionary, detect/detections.parquet).
DETECTIONS_COLUMNS = [
    "det_id", "pass_id", "time_utc", "x_m", "y_m", "peak_ratio_vv_db", "peak_ratio_vh_db",
    "pol_agree", "n_px", "size_class", "ghost", "p_boat",
]  # fmt: skip


def check_detections(df: pd.DataFrame) -> pd.DataFrame:
    missing = set(DETECTIONS_COLUMNS) - set(df.columns)
    assert not missing, f"detections missing {missing}"
    assert df["p_boat"].between(0, 1).all(), "p_boat outside [0, 1]"
    assert df["size_class"].isin(["small", "medium", "large"]).all()
    assert len(df) == 0 or str(df["time_utc"].dt.tz) == "UTC", "time_utc must be tz-aware UTC"
    return df[DETECTIONS_COLUMNS]


def cell_id(x_m: np.ndarray, y_m: np.ndarray, cfg: dict[str, Any] = CFG) -> np.ndarray:
    """TODO(P3): the cell_id format is P3's; this stand-in names 2 km cells by grid index."""
    if cfg["x0"] is None or cfg["y0"] is None:
        raise ValueError("x0/y0 not set: needs P1's config (TODO(P1))")
    ix = np.floor((np.asarray(x_m) - cfg["x0"]) / cfg["cell_m"]).astype(int)
    iy = np.floor((np.asarray(y_m) - cfg["y0"]) / cfg["cell_m"]).astype(int)
    return np.char.add(np.char.add(ix.astype(str), "_"), iy.astype(str))


# ---------------------------------------------------------------- simulator stand-in
# TODO(P1): replace with sim/. Renders int16 dB x 100 chips with gamma speckle (issue 8).
# The sea levels and meta values below are simulator settings only, never used on real data.
SIM_SEA_DB = {"vv": -20.0, "vh": -27.0}
SIM_META = {"prf_hz": 1700.0, "slant_range_m": 850_000.0, "sat_speed_ms": 7600.0, "heading_deg": 350.0}


@dataclass
class SimScene:
    vv: np.ndarray  # int16, dB x 100, as raw/s1/*.tif delivers it
    vh: np.ndarray
    meta: dict[str, Any]
    land: np.ndarray  # uint8, 1 = masked
    static: np.ndarray
    boats: pd.DataFrame  # truth: row, col, n_px, excess_db
    ghosts: pd.DataFrame  # truth: row, col of planted azimuth ghosts


def _db100(lin: np.ndarray) -> np.ndarray:
    return np.clip(np.round(1000 * np.log10(lin)), -32768, 32767).astype(np.int16)


def make_scene(
    seed: int,
    shape: tuple[int, int] = (400, 400),
    n_boats: int = 0,
    boat_excess_db: float | tuple[float, float] = 15.0,
    n_ships: int = 0,
    ship_excess_db: float = 40.0,
    ghost_drop_db: float = 25.0,
    land_cols: int = 0,
    L: float = 4.4,
    pass_id: str = "sim0",
    time_utc: str = "2026-11-01T06:30:00Z",
) -> SimScene:
    """Gamma-speckled sea, boats of 1-4 px added in linear power, optional ships with ghosts.

    land_cols: that many leftmost columns are land (bright, masked). Ship ghosts sit at
    the formula offset along heading_deg, ghost_drop_db below the ship.
    """
    rng = np.random.default_rng(seed)
    meta: dict[str, Any] = {"pass_id": pass_id, "start_time": time_utc, "x_left": 500_000.0,
                            "y_top": 5_700_000.0, **SIM_META}  # fmt: skip
    px = P4_DEFAULTS["pixel_m"]
    offset = P4_DEFAULTS["radar_wavelength_m"] * meta["slant_range_m"] * meta["prf_hz"] / (2 * meta["sat_speed_ms"])
    h = np.deg2rad(meta["heading_deg"])
    drow, dcol = -np.cos(h) * offset / px, np.sin(h) * offset / px

    imgs = {}
    for pol, db in SIM_SEA_DB.items():
        imgs[pol] = 10 ** (db / 10) * rng.gamma(L, 1 / L, size=shape)
    land = np.zeros(shape, np.uint8)
    land[:, :land_cols] = 1
    for img in imgs.values():
        img[:, :land_cols] *= 100  # land is bright

    margin = 30 + land_cols
    boats = []
    for _ in range(n_boats):
        r, c = rng.integers(30, shape[0] - 30), rng.integers(margin, shape[1] - 30)
        n = int(rng.integers(1, 5))
        ex = boat_excess_db if np.isscalar(boat_excess_db) else rng.uniform(*boat_excess_db)
        cells = [(r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)][:n]
        for pol, img in imgs.items():
            for rr, cc in cells:
                img[rr, cc] += 10 ** ((SIM_SEA_DB[pol] + ex) / 10)  # linear, never dB
        boats.append({"row": r + 0.5 * (n > 2), "col": c + 0.5 * (n > 1), "n_px": n, "excess_db": ex})

    ghosts = []
    for _ in range(n_ships):
        # ship and ghost both inside the scene and off land
        for _try in range(1000):
            r, c = rng.integers(10, shape[0] - 10), rng.integers(margin, shape[1] - 10)
            side = rng.choice([-1, 1])
            gr, gc = round(r + side * drow), round(c + side * dcol)
            if 10 <= gr < shape[0] - 10 and margin <= gc < shape[1] - 10:
                break
        else:
            raise ValueError("scene too small for the ghost offset")
        for pol, img in imgs.items():
            img[r : r + 6, c : c + 6] += 10 ** ((SIM_SEA_DB[pol] + ship_excess_db) / 10)
            img[gr : gr + 2, gc : gc + 2] += 10 ** ((SIM_SEA_DB[pol] + ship_excess_db - ghost_drop_db) / 10)
        ghosts.append({"row": gr + 0.5, "col": gc + 0.5, "ship_row": r + 2.5, "ship_col": c + 2.5})

    return SimScene(
        vv=_db100(imgs["vv"]), vh=_db100(imgs["vh"]), meta=meta, land=land,
        static=np.zeros(shape, np.uint8), boats=pd.DataFrame(boats, columns=["row", "col", "n_px", "excess_db"]),
        ghosts=pd.DataFrame(ghosts, columns=["row", "col", "ship_row", "ship_col"]),
    )  # fmt: skip
