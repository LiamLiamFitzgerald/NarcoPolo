import hashlib
import json
import struct
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core.config import load
from core.grid import FINE, _origin
from sim import scenes
from sim.world import SimWorld

SEED = 20261127


def _read_tif(path: Path) -> tuple[np.ndarray, tuple[float, float]]:
    """Minimal reader for the files write_scenes makes: (bands x rows x cols int16, top-left x, y)."""
    b = path.read_bytes()
    assert b[:4] == b"II*\x00"
    (ifd,) = struct.unpack_from("<I", b, 4)
    (n,) = struct.unpack_from("<H", b, ifd)
    tags = {}
    for i in range(n):
        tag, typ, count, val = struct.unpack_from("<HHII", b, ifd + 2 + 12 * i)
        size = {3: 2, 4: 4, 12: 8}[typ] * count
        fmt = {3: "H", 4: "I", 12: "d"}[typ]
        if size <= 4:
            tags[tag] = struct.unpack_from(f"<{count}{fmt}", b, ifd + 2 + 12 * i + 8)
        else:
            tags[tag] = struct.unpack_from(f"<{count}{fmt}", b, val)
    w, h = tags[256][0], tags[257][0]
    bands = [np.frombuffer(b, "<i2", w * h, off).reshape(h, w) for off in tags[273]]
    tie = tags[33922]
    return np.stack(bands), (tie[3], tie[4])


def _world(ghost: bool = True) -> SimWorld:
    """Two cells by two cells of calm sea, one pass over it, one boat, one ship with its ghost."""
    cfg, _ = load("config.yaml")
    x0, y0 = _origin()
    fine = pd.DataFrame(
        {
            "cell_id": ["2000_10_5", "2000_11_5", "2000_10_6", "2000_11_6"],
            "ix": [10, 11, 10, 11],
            "iy": [5, 5, 6, 6],
            "sea_frac": 1.0,
            "static_frac": 0.0,
        }
    )
    t = pd.Timestamp("2026-08-01T06:00", tz="UTC")
    passes = pd.DataFrame(
        {"pass_id": ["pass_000"], "day": [1], "time_utc": [t], "a": [0.0], "b": [75.0]}
    )
    bx, by = x0 + 10.3 * FINE, y0 + 5.5 * FINE
    sx, sy = x0 + 10.2 * FINE, y0 + 6.2 * FINE
    off = cfg["sim"]["ghost_offset_m"]
    det = pd.DataFrame(
        {
            "det_id": ["det_0", "det_1"],
            "pass_id": "pass_000",
            "time_utc": t,
            "x_m": [bx, sx + off],
            "y_m": [by, sy],
            "peak_ratio_vv_db": [9.0, 4.0],
            "peak_ratio_vh_db": [6.0, 1.0],
            "pol_agree": True,
            "n_px": [1, 2],
            "size_class": ["small", "large"],
            "ghost": [False, True],
            "p_boat": [0.8, 0.03],
        }
    )
    ships = pd.DataFrame(
        {
            "day": [1.2],
            "cell": [0],
            "planted": [False],
            "x_m": [sx],
            "y_m": [sy],
            "duration_min": [60.0],
        }
    )
    if not ghost:
        det, ships = det.iloc[:1], ships.iloc[:0]
    return SimWorld(
        config=cfg,
        seed=SEED,
        start=date(2026, 7, 31),
        days=3,
        fine=fine,
        weather=pd.DataFrame({"wind_ms": [3.0] * 3, "hs_m": [0.5] * 3, "rough": [False] * 3}),
        passes=passes,
        boats=pd.DataFrame(),
        ships=ships,
        detections=det,
    )


@pytest.fixture
def raw(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    return tmp_path / "raw"


def _files(root: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((root / "s1").iterdir())
    }


def test_same_seed_same_bytes(raw):
    scenes.write_scenes(_world())
    first = _files(raw)
    assert len(first) == 2  # one .tif and one .json for the one pass
    scenes.write_scenes(_world())
    assert _files(raw) == first


def test_metadata_has_every_field(raw):
    scenes.write_scenes(_world())
    meta = json.loads(next((raw / "s1").glob("*.json")).read_text())
    for key in (
        "scene_id",
        "start_time",
        "orbit_direction",
        "relative_orbit",
        "footprint",
        "incidence_min",
        "incidence_max",
        "prf_hz",
        "slant_range_m",
        "satellite_speed_ms",
        "heading_deg",
    ):
        assert key in meta
    assert meta["start_time"].endswith("+00:00")
    assert meta["footprint"].startswith("POLYGON")


def _pixel(origin: tuple[float, float], x: float, y: float) -> tuple[int, int]:
    return int((origin[1] - y) // 10), int((x - origin[0]) // 10)


def test_boat_brighter_than_clutter_in_linear_power(raw):
    scenes.write_scenes(_world(ghost=False))
    img, origin = _read_tif(next((raw / "s1").glob("*.tif")))
    lin = 10 ** (img[0].astype(float) / 100 / 10)  # VV, dB x 100 -> linear
    x0, y0 = _origin()
    r, c = _pixel(origin, x0 + 10.3 * FINE, y0 + 5.5 * FINE)
    # 9 dB over the clutter mean in linear power, so the boat pixel is several times the mean
    assert lin[r, c] > 4 * np.median(lin)
    # speckle is gamma with L = 4.4: mean / variance of linear power is about L / mean^2
    sea = lin[: lin.shape[0] // 2]
    assert abs(sea.mean() ** 2 / sea.var() - 4.4) < 0.5


def test_ghost_drawn_at_the_offset(raw):
    w = _world()
    scenes.write_scenes(w)
    img, origin = _read_tif(next((raw / "s1").glob("*.tif")))
    lin = 10 ** (img[0].astype(float) / 1000)
    ship = w.ships.iloc[0]
    off = w.config["sim"]["ghost_offset_m"]
    rs, cs = _pixel(origin, ship.x_m, ship.y_m)
    rg, cg = _pixel(origin, ship.x_m + off, ship.y_m)
    assert rg == rs and cg - cs == off // 10
    assert lin[rs, cs] > lin[rg, cg] > 2 * np.median(lin)  # the ship outshines its ghost
