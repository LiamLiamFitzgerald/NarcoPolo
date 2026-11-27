# pyright: reportCallIssue=false, reportArgumentType=false, reportOperatorIssue=false
# (pandas and numpy scalar typing noise, as in simulate.py; the tests check the values)
"""Radar scene chips shaped like raw/s1 (issue 8): one GeoTIFF and one metadata JSON per pass. Reads the SimWorld only.

Each chip is the pass footprint inside a small window around the planted drop site, at 10 m on the region grid
(origin x0, y0). Clutter is gamma speckle with L = 4.4 in linear power; every target (boat, false alarm, ghost,
ship, turbine) is added in linear power, never in dB. What to draw comes from the world: world.detections for
boats, false alarms and ghosts, world.ships for the bright ships that leave the ghosts.
"""

import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pandas as pd

from core import io
from core.grid import FINE, _origin
from sim.world import SimWorld

PX = 10  # m per pixel (Data dictionary: raw/s1 is 10 m)
ENL = 4.4  # equivalent number of looks, the gamma shape (issue 8)
# TODO(P1): not in the spec. Chip size, clutter levels and target brightness chosen so a chip is a few MB and
# boats, ships and turbines stand out the way they do in real calm-sea Sentinel-1 IW scenes. Asked on #92.
CHIP_HALF_M = 3000  # chip = centre +- this, so 600 x 600 px
SEA_DB = (-20.0, -27.0)  # mean sea sigma0, VV and VH
LAND_DB = -5.0
SHIP_DB = 20.0  # ship peak over the sea mean, both bands
TURBINE_DB = 25.0
# TODO(P1): Sentinel-1 IW annotation values (typical, not from the spec). Slant range is derived so the
# azimuth-ambiguity offset lambda * R * PRF / (2 V) equals sim.ghost_offset_m.
WAVELENGTH_M = 0.05547  # C band, 5.405 GHz
PRF_HZ = 1717.0
SAT_SPEED_MS = 7600.0
INCIDENCE = (29.1, 46.0)
ORBIT = ("DESCENDING", 1, 190.0)  # direction, relative orbit, heading_deg


def _chip(world: SimWorld) -> tuple[float, float, float, float]:
    """(xmin, ymin, xmax, ymax) on the 10 m grid: CHIP_HALF_M around the planted site, inside the fine cells."""
    x0, y0 = _origin()
    ix, iy = world.fine["ix"], world.fine["iy"]
    bx = (
        x0 + ix.min() * FINE,
        y0 + iy.min() * FINE,
        x0 + (ix.max() + 1) * FINE,
        y0 + (iy.max() + 1) * FINE,
    )
    planted = world.ships[world.ships["planted"]] if len(world.ships) else world.ships
    if len(planted):
        cx, cy = float(planted["x_m"].iloc[0]), float(planted["y_m"].iloc[0])
    else:
        cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
    snap = lambda v, o: o + round((v - o) / PX) * PX
    return (
        max(bx[0], snap(cx - CHIP_HALF_M, x0)),
        max(bx[1], snap(cy - CHIP_HALF_M, y0)),
        min(bx[2], snap(cx + CHIP_HALF_M, x0)),
        min(bx[3], snap(cy + CHIP_HALF_M, y0)),
    )


def _land(world: SimWorld, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """True on land: outside every fine cell, or past a shore cell's sea share (the shore runs along +y)."""
    x0, y0 = _origin()
    sea = {(int(r.ix), int(r.iy)): float(r.sea_frac) for r in world.fine.itertuples()}
    ci, cj = ((xs - x0) // FINE).astype(int), ((ys - y0) // FINE).astype(int)
    frac = np.vectorize(lambda i, j: sea.get((i, j), 0.0))(ci[None, :], cj[:, None])
    return (ys[:, None] - (y0 + cj[:, None] * FINE)) >= frac * FINE


def _add(
    img: np.ndarray,
    mean: np.ndarray,
    xmin: float,
    ymax: float,
    x: float,
    y: float,
    db: float,
    n: int,
) -> None:
    """Add a target of n pixels (a row along +x) whose peak is `db` over the local mean, in linear power."""
    r, c = int((ymax - y) // PX), int((x - xmin) // PX)
    h, w = img.shape
    for k in range(max(1, n)):
        if 0 <= r < h and 0 <= c + k < w:
            img[r, c + k] += mean[r, c + k] * max(10 ** (db / 10) - 1, 0.0)


def _render(world: SimWorld, k: int, chip: tuple[float, float, float, float]) -> np.ndarray:
    xmin, ymin, xmax, ymax = chip
    xs = np.arange(xmin, xmax, PX) + PX / 2
    ys = np.arange(ymax, ymin, -PX) - PX / 2  # north-up: row 0 is the top
    land = _land(world, xs, ys)
    rng = np.random.default_rng([world.seed + world.config["sim"]["seed_offsets"]["scenes"], k])
    p = world.passes.iloc[k]
    dets = world.detections[world.detections["pass_id"] == p["pass_id"]]
    x0, _ = _origin()
    on_day = (
        world.ships[world.ships["day"].astype(int) == int(p["day"])]
        if len(world.ships)
        else world.ships
    )
    ships = on_day[((on_day["x_m"] - x0) / FINE).between(p["a"], p["b"])] if len(on_day) else on_day
    turbines = world.fine[world.fine["static_frac"] > 0]
    out = []
    for band, sea_db in enumerate(SEA_DB):
        mean = np.where(land, 10 ** (LAND_DB / 10), 10 ** (sea_db / 10))
        img = mean * rng.gamma(ENL, 1 / ENL, mean.shape)
        col = "peak_ratio_vv_db" if band == 0 else "peak_ratio_vh_db"
        for d in dets.itertuples():
            _add(img, mean, xmin, ymax, d.x_m, d.y_m, getattr(d, col), int(d.n_px))
        for s in ships.itertuples():
            _add(img, mean, xmin, ymax, s.x_m, s.y_m, SHIP_DB, 3)
        for t in turbines.itertuples():
            _add(
                img,
                mean,
                xmin,
                ymax,
                x0 + (t.ix + 0.5) * FINE,
                _origin()[1] + (t.iy + 0.5) * FINE,
                TURBINE_DB,
                1,
            )
        out.append(np.clip(np.round(100 * 10 * np.log10(img)), -32768, 32767).astype("<i2"))
    return np.stack(out)


def _geotiff(path: Path, bands: np.ndarray, xmin: float, ymax: float) -> None:
    """Uncompressed little-endian GeoTIFF: int16 bands as separate planes, EPSG:32629, 10 m pixels, top-left tie."""
    nb, h, w = bands.shape
    geokeys = [
        1,
        1,
        0,
        3,
        1024,
        0,
        1,
        1,
        1025,
        0,
        1,
        1,
        3072,
        0,
        1,
        32629,
    ]  # projected, pixel-is-area, UTM 29N
    data = [b.tobytes() for b in bands]
    extra = [  # (tag, type, values) whose values do not fit in 4 bytes, written after the IFD
        (33550, 12, [float(PX), float(PX), 0.0]),
        (33922, 12, [0.0, 0.0, 0.0, float(xmin), float(ymax), 0.0]),
        (34735, 3, geokeys),
    ]
    tags = [
        (256, 4, [w]),
        (257, 4, [h]),
        (258, 3, [16] * nb),
        (259, 3, [1]),
        (262, 3, [1]),
        (273, 4, [0] * nb),
        (277, 3, [nb]),
        (278, 4, [h]),
        (279, 4, [len(d) for d in data]),
        (284, 3, [2]),
        (338, 3, [0] * (nb - 1)),
        (339, 3, [2] * nb),
        *extra,
    ]
    fmt = {3: "H", 4: "I", 12: "d"}
    size = {3: 2, 4: 4, 12: 8}
    ifd_len = 2 + 12 * len(tags) + 4
    pos = 8 + ifd_len
    blobs, where = [], {}
    for tag, typ, vals in tags:
        n = size[typ] * len(vals)
        if n > 4:
            where[tag] = pos
            blobs.append((tag, typ, vals))
            pos += n + (n % 2)
    offsets = []
    for d in data:
        offsets.append(pos)
        pos += len(d)
    tags = [(t, ty, offsets if t == 273 else v) for t, ty, v in tags]
    out = bytearray(b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", len(tags)))
    for tag, typ, vals in tags:
        n = size[typ] * len(vals)
        if n > 4:
            out += struct.pack("<HHII", tag, typ, len(vals), where[tag])
        else:
            out += struct.pack("<HHI", tag, typ, len(vals)) + struct.pack(
                f"<{len(vals)}{fmt[typ]}", *vals
            ).ljust(4, b"\0")
    out += struct.pack("<I", 0)
    for tag, typ, _ in blobs:
        vals = offsets if tag == 273 else next(v for t, _, v in tags if t == tag)
        b = struct.pack(f"<{len(vals)}{fmt[typ]}", *vals)
        out += b + b"\0" * (len(b) % 2)
    for d in data:
        out += d
    path.write_bytes(bytes(out))


def _meta(world: SimWorld, k: int, scene_id: str) -> dict:
    x0, y0 = _origin()
    p = world.passes.iloc[k]
    top = y0 + (int(world.fine["iy"].max()) + 1) * FINE
    xa, xb = x0 + p["a"] * FINE, x0 + p["b"] * FINE
    ring = f"{xa:.1f} {y0:.1f}, {xb:.1f} {y0:.1f}, {xb:.1f} {top:.1f}, {xa:.1f} {top:.1f}, {xa:.1f} {y0:.1f}"
    off = float(world.config["sim"]["ghost_offset_m"])
    return {
        "scene_id": scene_id,
        "pass_id": str(p["pass_id"]),
        "start_time": pd.Timestamp(p["time_utc"]).isoformat(),
        "orbit_direction": ORBIT[0],
        "relative_orbit": ORBIT[1],
        "footprint": f"POLYGON (({ring}))",
        "footprint_crs": "EPSG:32629",
        "incidence_min": INCIDENCE[0],
        "incidence_max": INCIDENCE[1],
        "prf_hz": PRF_HZ,
        "slant_range_m": round(2 * SAT_SPEED_MS * off / (WAVELENGTH_M * PRF_HZ), 1),
        "satellite_speed_ms": SAT_SPEED_MS,
        "heading_deg": ORBIT[2],
    }


def write_scenes(world: SimWorld) -> None:
    """raw/s1/<hash>.tif and .json for every pass whose footprint reaches the chip; same seed, same bytes."""
    out = io.raw_root() / "s1"
    out.mkdir(parents=True, exist_ok=True)
    x0, _ = _origin()
    chip = _chip(world)
    for k, p in enumerate(world.passes.itertuples()):
        xmin = max(chip[0], x0 + p.a * FINE)
        xmax = min(chip[2], x0 + p.b * FINE)
        xmin, xmax = x0 + np.ceil((xmin - x0) / PX) * PX, x0 + np.floor((xmax - x0) / PX) * PX
        if xmax - xmin < PX:
            continue  # this pass never covered the chip
        h = hashlib.sha256(f"{world.seed}-{p.pass_id}".encode()).hexdigest()[:16]
        clip = (float(xmin), chip[1], float(xmax), chip[3])
        _geotiff(out / f"{h}.tif", _render(world, k, clip), clip[0], clip[3])
        (out / f"{h}.json").write_text(json.dumps(_meta(world, k, h), indent=1))
