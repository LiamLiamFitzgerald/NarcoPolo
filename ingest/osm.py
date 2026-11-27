"""OpenStreetMap via Overpass: piers, slipways, harbours (+ roads within 200 m) and the coastline."""

import json
from pathlib import Path

from ingest import _stub


def fetch_piers(bbox: _stub.Bbox) -> Path:
    """raw/osm_piers.geojson. Stub: an empty FeatureCollection."""

    def write(path: Path) -> None:
        path.write_text(json.dumps({"type": "FeatureCollection", "features": []}, indent=1))

    return _stub.get(_stub.request("osm_piers", bbox), "osm_piers.geojson", write)


def fetch_coastline(bbox: _stub.Bbox) -> Path:
    """raw/coastline.gpkg, layer coastline. Stub: no features."""
    write = lambda p: _stub.empty_gpkg(p, "coastline", "LineString")
    return _stub.get(_stub.request("coastline", bbox), "coastline.gpkg", write)
