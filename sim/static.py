"""Static raw layers: osm_piers.geojson, coastline.gpkg, inshore/*.gpkg, infomar_bathy.tif. Reads the SimWorld only;
the shore, piers and inshore band come from sim.simulate._make_map so they cannot drift apart."""

import json
import sqlite3
import struct
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, box

from core.grid import FINE, _origin
from core.io import raw_root
from sim.world import SimWorld

PIXEL_M = 250.0


def _gpkg(frame: gpd.GeoDataFrame, path: Path, layer: str) -> None:
    frame.to_crs(4326).to_file(path, layer=layer, driver="GPKG")
    db = sqlite3.connect(
        path
    )  # GeoPackage stamps the write time; pin it so the same seed gives the same bytes
    with db:
        db.execute("UPDATE gpkg_contents SET last_change = '2000-01-01T00:00:00.000Z'")
    db.close()
    # SQLite's header write counter (bytes 24-27, copied at 92-95) varies with how many writes the driver made
    b = bytearray(path.read_bytes())
    b[24:28] = b[92:96] = (1).to_bytes(4, "big")
    path.write_bytes(bytes(b))


def _geotiff(path: Path, depth: np.ndarray, x_left: float, y_top: float) -> None:
    """Minimal uncompressed float32 GeoTIFF in EPSG:32629 (no raster library is installed)."""
    h, w = depth.shape
    data = depth.astype("<f4").tobytes()
    geokeys = (
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
    )  # projected, pixel-is-area, EPSG:32629
    extra = (
        struct.pack("<3d", PIXEL_M, PIXEL_M, 0)
        + struct.pack("<6d", 0, 0, 0, x_left, y_top, 0)
        + struct.pack("<16H", *geokeys)
    )
    n_tags = 13
    data_at = 8 + 2 + n_tags * 12 + 4
    extra_at = data_at + len(data)
    # (tag, type, count, value), sorted by tag; type 3 = SHORT, 4 = LONG, 12 = DOUBLE
    tags = [
        (256, 4, 1, w), (257, 4, 1, h), (258, 3, 1, 32), (259, 3, 1, 1), (262, 3, 1, 1), (273, 4, 1, data_at),
        (277, 3, 1, 1), (278, 4, 1, h), (279, 4, 1, len(data)), (339, 3, 1, 3),
        (33550, 12, 3, extra_at), (33922, 12, 6, extra_at + 24), (34735, 3, 16, extra_at + 72),
    ]  # fmt: skip
    body = struct.pack("<2sHI", b"II", 42, 8) + struct.pack("<H", n_tags)
    for t, ty, c, v in tags:  # a SHORT value sits in the first two bytes of the 4-byte value field
        body += (
            struct.pack("<HHIHH", t, ty, c, v, 0)
            if ty == 3 and c == 1
            else struct.pack("<HHII", t, ty, c, v)
        )
    path.write_bytes(body + struct.pack("<I", 0) + data + extra)


def write_static(world: SimWorld) -> None:
    from sim.simulate import NX, NY, SHORE_FRAC, _make_map  # here: simulate imports this module

    root = raw_root()
    (root / "inshore").mkdir(parents=True, exist_ok=True)
    x0, y0 = _origin()
    m = _make_map(world.config)
    shore_y = y0 + (NY - 1) * FINE + SHORE_FRAC * FINE
    right, top = x0 + NX * FINE, y0 + NY * FINE

    piers = m["piers"].to_crs(4326)
    feats = [
        {
            "type": "Feature",
            "properties": {
                "pier_id": r.pier_id,
                "name": r.name,
                "road_access": "yes" if r.road_access else "no",
            },
            "geometry": {
                "type": "Point",
                "coordinates": [round(r.geometry.x, 6), round(r.geometry.y, 6)],
            },
        }
        for r in piers.itertuples()
    ]
    (root / "osm_piers.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, indent=1)
    )

    def frame(geom):
        return gpd.GeoDataFrame({"id": [0]}, geometry=[geom], crs=32629)

    _gpkg(
        frame(LineString([(x0, shore_y), (right, shore_y)])), root / "coastline.gpkg", "coastline"
    )
    # the dataset's inshore band is 5 km wide, measured the way _make_map does (from the top of the shore row), sea side only
    _gpkg(
        frame(box(x0, top - 5000, right, shore_y)),
        root / "inshore" / "inshore_grounds.gpkg",
        "inshore_grounds",
    )
    _gpkg(
        frame(box(x0, y0, right, shore_y)), root / "inshore" / "survey_extent.gpkg", "survey_extent"
    )  # gap 7

    # depth (m, negative down) grows with distance from the shore, 1 m per 100 m, capped at 200 m
    nx, ny = int(NX * FINE / PIXEL_M), int(NY * FINE / PIXEL_M)
    dist = np.maximum(shore_y - (y0 + (np.arange(ny) + 0.5) * PIXEL_M), 0)[
        ::-1
    ]  # row 0 is the top (north) row
    depth = -np.minimum(dist / 100, 200)[:, None] * np.ones((1, nx))
    _geotiff(root / "infomar_bathy.tif", depth, x0, top)
