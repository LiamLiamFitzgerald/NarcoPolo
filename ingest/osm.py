"""OpenStreetMap via Overpass: piers, slipways, harbours (+ road access within 200 m) and the coastline.

Road access is decided by Overpass itself (`around`), so ingest computes no geometry.
"""

import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import LineString

from core.io import raw_root
from ingest.cache import cached, record

# TODO(P2): move to config.yaml `ingest:` (issues #215, #216)
_OVERPASS = "https://overpass-api.de/api/interpreter"
_ROAD_M = 200  # docs/specs/P2.md step 8: highway=* within 200 m
_LICENCE = "Open Database License (ODbL) 1.0; © OpenStreetMap contributors"
_SITE_TAGS = ("man_made", "leisure", "harbour")

Bbox = tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max (WGS84)


def _overpass(query: str) -> dict:
    data = urllib.parse.urlencode({"data": query}).encode()
    req = urllib.request.Request(_OVERPASS, data=data, headers={"User-Agent": "narcopolo-ingest"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)


def _box(bbox: Bbox) -> str:
    lon_min, lat_min, lon_max, lat_max = bbox
    return f"{lat_min},{lon_min},{lat_max},{lon_max}"  # Overpass order: S, W, N, E


def _get(source: str, query: str, rel: str, write: Callable[[Path, dict], None]) -> Path:
    req = {"source": source, "endpoint": _OVERPASS, "query": query}
    if (hit := cached(req)) is not None:
        return hit
    answer = _overpass(query)
    path = raw_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    write(path, answer)
    record(req, path, _LICENCE)
    return path


def fetch_piers(bbox: Bbox) -> Path:
    """raw/osm_piers.geojson: one Point per site (node position or Overpass's way/relation centre) with
    pier_id ("<type>/<osm id>"), name, the matching tags and road_access "yes"/"no"."""
    b = _box(bbox)
    query = (
        "[out:json][timeout:600];\n"
        f'(nwr["man_made"="pier"]({b});nwr["leisure"="slipway"]({b});nwr["harbour"]({b});)->.sites;\n'
        f'way(around.sites:{_ROAD_M})["highway"]->.roads;\n'
        f"nwr.sites(around.roads:{_ROAD_M})->.reached;\n"
        ".sites out center tags;\n"
        ".reached out ids;"
    )

    def write(path: Path, answer: dict) -> None:
        elements = answer["elements"]
        reached = {(e["type"], e["id"]) for e in elements if "tags" not in e}  # `out ids` rows
        features = []
        for e in elements:
            if "tags" not in e:
                continue
            at = e if "lat" in e else e["center"]
            props = {"pier_id": f"{e['type']}/{e['id']}", "name": e["tags"].get("name")}
            props |= {k: e["tags"].get(k) for k in _SITE_TAGS}
            props["road_access"] = "yes" if (e["type"], e["id"]) in reached else "no"
            geometry = {"type": "Point", "coordinates": [at["lon"], at["lat"]]}
            features.append({"type": "Feature", "properties": props, "geometry": geometry})
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, indent=1))

    return _get("osm_piers", query, "osm_piers.geojson", write)


def fetch_coastline(bbox: Bbox) -> Path:
    """raw/coastline.gpkg, layer coastline: natural=coastline ways as Overpass gives them (lines), id = way id."""
    query = f'[out:json][timeout:600];\nway["natural"="coastline"]({_box(bbox)});\nout geom;'

    def write(path: Path, answer: dict) -> None:
        ways = [e for e in answer["elements"] if e["type"] == "way"]
        lines = [LineString([(p["lon"], p["lat"]) for p in w["geometry"]]) for w in ways]
        frame = gpd.GeoDataFrame({"id": [w["id"] for w in ways]}, geometry=lines, crs=4326)
        frame["id"] = frame["id"].astype("int64")
        pyogrio.write_dataframe(frame, path, layer="coastline", geometry_type="LineString")

    return _get("coastline", query, "coastline.gpkg", write)
