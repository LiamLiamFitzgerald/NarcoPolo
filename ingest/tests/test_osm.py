"""osm against a fake Overpass that serves the simulator's piers and coastline: the files must give them back."""

import json
import socket

import geopandas as gpd
import pyogrio
import pytest

from ingest import osm
from ingest.tests.conftest import CFG

B = CFG["region_bbox"]
BBOX = (B["lon_min"], B["lat_min"], B["lon_max"], B["lat_max"])


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    return tmp_path


def _fake_overpass(simraw):
    """Overpass JSON built from the simulator: each pier a node (road access from `out ids`), one slipway as a
    way with a centre (no road), and the coastline as ways with geometry."""
    piers = gpd.read_file(simraw / "osm_piers.geojson")
    coast = pyogrio.read_dataframe(simraw / "coastline.gpkg")
    queries = []

    def answer(query):
        queries.append(query)
        if "coastline" in query:
            ways = [
                {
                    "type": "way",
                    "id": int(i),
                    "geometry": [{"lon": x, "lat": y} for x, y in g.coords],
                }
                for i, g in zip(coast["id"], coast.geometry, strict=True)
            ]
            return {"elements": ways}
        sites = [
            {
                "type": "node",
                "id": i,
                "lat": y,
                "lon": x,
                "tags": {"man_made": "pier", "name": n},
            }
            for i, (x, y, n) in enumerate(
                zip(piers.geometry.x, piers.geometry.y, piers["name"], strict=True)
            )
        ]
        slip = {
            "type": "way",
            "id": 99,
            "center": {"lat": 51.5, "lon": -9.0},
            "tags": {"leisure": "slipway"},
        }
        reached = [
            {"type": "node", "id": i} for i, a in enumerate(piers["road_access"]) if a == "yes"
        ]
        return {"elements": [*sites, slip, *reached]}

    return piers, coast, queries, answer


def test_fetch_piers_recovers_simulator_piers(simraw, raw, monkeypatch):
    piers, _, queries, answer = _fake_overpass(simraw)
    monkeypatch.setattr(osm, "_overpass", answer)
    path = osm.fetch_piers(BBOX)
    assert path == raw / "osm_piers.geojson"
    got = gpd.read_file(path)
    assert len(got) == len(piers) + 1
    sim_part = got.iloc[: len(piers)]
    assert list(sim_part["name"]) == list(piers["name"])
    assert list(sim_part["road_access"]) == list(
        piers["road_access"]
    )  # same "yes"/"no" column P3 reads
    assert sim_part.geometry.geom_equals(piers.geometry).all()
    slip = got.iloc[-1]
    assert (slip["pier_id"], slip["leisure"], slip["road_access"]) == ("way/99", "slipway", "no")
    assert (slip.geometry.x, slip.geometry.y) == (-9.0, 51.5)
    (q,) = queries
    box = f"{B['lat_min']},{B['lon_min']},{B['lat_max']},{B['lon_max']}"
    for part in (
        '"man_made"="pier"',
        '"leisure"="slipway"',
        '["harbour"]',
        '["highway"]',
        ":200)",
        box,
    ):
        assert part in q


def test_fetch_coastline_recovers_simulator_lines(simraw, raw, monkeypatch):
    _, coast, _, answer = _fake_overpass(simraw)
    monkeypatch.setattr(osm, "_overpass", answer)
    path = osm.fetch_coastline(BBOX)
    info = pyogrio.read_info(path, layer="coastline")
    sim_info = pyogrio.read_info(simraw / "coastline.gpkg", layer="coastline")
    assert (info["geometry_type"], info["crs"], list(info["fields"])) == (
        sim_info["geometry_type"],
        sim_info["crs"],
        list(sim_info["fields"]),
    )
    got = pyogrio.read_dataframe(path, layer="coastline")
    assert list(got["id"]) == list(coast["id"])
    assert got.geometry.geom_equals(coast.geometry).all()


def test_rerun_downloads_nothing_and_records_odbl(simraw, raw, monkeypatch):
    *_, answer = _fake_overpass(simraw)
    monkeypatch.setattr(osm, "_overpass", answer)
    piers, coast = osm.fetch_piers(BBOX), osm.fetch_coastline(BBOX)
    files = json.loads((raw / "manifest.json").read_text())["files"]
    assert {files[p.name]["licence"] for p in (piers, coast)} == {osm._LICENCE}
    assert "OpenStreetMap" in osm._LICENCE
    monkeypatch.setattr(osm, "_overpass", lambda q: pytest.fail("cached request hit the network"))
    assert (osm.fetch_piers(BBOX), osm.fetch_coastline(BBOX)) == (piers, coast)
