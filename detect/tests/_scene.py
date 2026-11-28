"""Test-only scene builder: gamma-speckled chips with planted boats, ships and ghosts whose positions are known
exactly (sim/scenes.py renders whole passes from the SimWorld; these tests need a single controlled chip)."""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from detect._common import CFG

# The sea levels and meta values below are simulator settings only, never used on real data.
SIM_SEA_DB = {"vv": -20.0, "vh": -27.0}
SIM_META = {
    "prf_hz": 1700.0,
    "slant_range_m": 850_000.0,
    "sat_speed_ms": 7600.0,
    "heading_deg": 350.0,
}


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
    px = CFG["pixel_m"]
    offset = (
        CFG["radar_wavelength_m"]
        * meta["slant_range_m"]
        * meta["prf_hz"]
        / (2 * meta["sat_speed_ms"])
    )
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
        boats.append(
            {"row": r + 0.5 * (n > 2), "col": c + 0.5 * (n > 1), "n_px": n, "excess_db": ex}
        )

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
            img[gr : gr + 2, gc : gc + 2] += 10 ** (
                (SIM_SEA_DB[pol] + ship_excess_db - ghost_drop_db) / 10
            )
        ghosts.append({"row": gr + 0.5, "col": gc + 0.5, "ship_row": r + 2.5, "ship_col": c + 2.5})

    return SimScene(
        vv=_db100(imgs["vv"]), vh=_db100(imgs["vh"]), meta=meta, land=land,
        static=np.zeros(shape, np.uint8), boats=pd.DataFrame(boats, columns=["row", "col", "n_px", "excess_db"]),
        ghosts=pd.DataFrame(ghosts, columns=["row", "col", "ship_row", "ship_col"]),
    )  # fmt: skip
