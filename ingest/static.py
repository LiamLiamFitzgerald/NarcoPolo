"""Inshore fishing layers (BIM / Marine Institute, data.gov.ie) with survey extent, and INFOMAR bathymetry."""

from pathlib import Path

import numpy as np

from ingest import _stub

_PX = 10.0  # m, the fixed region grid (issue 5)


def fetch_inshore() -> list[Path]:
    """raw/inshore/inshore_grounds.gpkg and raw/inshore/survey_extent.gpkg (issue 7). Stub: no features."""
    out = []
    for layer in ("inshore_grounds", "survey_extent"):
        req = _stub.request(f"inshore/{layer}", _stub.region())
        write = lambda p, layer=layer: _stub.empty_gpkg(p, layer, "Polygon")
        out.append(_stub.get(req, f"inshore/{layer}.gpkg", write))
    return out


def fetch_bathy() -> Path:
    """raw/infomar_bathy.tif, float32 depth (m). Stub: one NaN pixel at the grid origin."""
    cfg = _stub.config()
    depth = np.full((1, 1, 1), np.nan, dtype=np.float32)
    write = lambda p: _stub.geotiff(p, depth, float(cfg["x0"]), float(cfg["y0"]) + _PX, _PX)
    return _stub.get(_stub.request("infomar_bathy", _stub.region()), "infomar_bathy.tif", write)
