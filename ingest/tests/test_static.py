"""static against fake downloads that serve the simulator's inshore layers and bathymetry in delivery formats
(zipped shapefile, GeoJSON, zipped GeoTIFF): the raw/ files must give the simulator's data back."""

import json
import shutil
import socket
import zipfile
from pathlib import Path

import numpy as np
import pyogrio
import pytest
import rasterio

from ingest import static

LIC = "CC BY 4.0. Attribution line as configured"


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    return tmp_path / "raw"


@pytest.fixture
def served(simraw, tmp_path_factory):
    """url -> local file in the format a portal would deliver."""
    d = tmp_path_factory.mktemp("served")
    grounds = pyogrio.read_dataframe(simraw / "inshore" / "inshore_grounds.gpkg")
    pyogrio.write_dataframe(grounds, d / "net.shp")
    with zipfile.ZipFile(d / "net.zip", "w") as z:
        for f in d.glob("net.*"):
            if f.suffix != ".zip":
                z.write(f, f.name)
    extent = pyogrio.read_dataframe(simraw / "inshore" / "survey_extent.gpkg")
    pyogrio.write_dataframe(extent, d / "extent.geojson", driver="GeoJSON")
    with zipfile.ZipFile(d / "bathy.zip", "w") as z:
        z.write(simraw / "infomar_bathy.tif", "tiles/bathy.tif")
    return {
        f"https://portal.example/{n}?x=1": d / n for n in ("net.zip", "extent.geojson", "bathy.zip")
    }


def _configure(monkeypatch, served, calls):
    urls = list(served)
    monkeypatch.setattr(
        static,
        "_settings",
        lambda: {
            "inshore_layers": {"net": {"url": urls[0], "licence": LIC}},
            "survey_extent": {"url": urls[1], "licence": LIC},
            "infomar_bathy": {"url": urls[2], "licence": LIC},
        },
    )

    def download(url: str, dest: Path) -> None:
        calls.append(url)
        shutil.copy(served[url], dest)

    monkeypatch.setattr(static, "_download", download)


def _files(raw):
    return json.loads((raw / "manifest.json").read_text())["files"]


def test_inshore_recovers_simulator_layers(simraw, raw, monkeypatch, served):
    _configure(monkeypatch, served, [])
    paths = static.fetch_inshore()
    assert [p.relative_to(raw).as_posix() for p in paths] == [
        "inshore/net.gpkg",
        "inshore/survey_extent.gpkg",
    ]
    for got, sim_name in zip(paths, ("inshore_grounds", "survey_extent"), strict=True):
        a = pyogrio.read_dataframe(got, layer=got.stem)
        s = pyogrio.read_dataframe(simraw / "inshore" / f"{sim_name}.gpkg")
        assert a.crs == s.crs and len(a) == len(s)
        assert a.geometry.normalize().geom_equals_exact(s.geometry.normalize(), 1e-9).all()
        assert _files(raw)[got.relative_to(raw).as_posix()]["licence"] == LIC


def test_bathy_recovers_simulator_raster(simraw, raw, monkeypatch, served):
    _configure(monkeypatch, served, [])
    path = static.fetch_bathy()
    assert path == raw / "infomar_bathy.tif"
    with rasterio.open(path) as a, rasterio.open(simraw / "infomar_bathy.tif") as s:
        assert (a.crs, a.transform, a.dtypes) == (s.crs, s.transform, s.dtypes)
        np.testing.assert_array_equal(a.read(), s.read())  # NaN stays NaN
    assert _files(raw)["infomar_bathy.tif"]["licence"] == LIC


def test_rerun_downloads_nothing(raw, monkeypatch, served):
    calls = []
    _configure(monkeypatch, served, calls)
    first = (static.fetch_inshore(), static.fetch_bathy())
    assert len(calls) == 3
    assert (static.fetch_inshore(), static.fetch_bathy()) == first
    assert len(calls) == 3


def test_zip_without_one_tif_fails(raw, monkeypatch, served, tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("readme.txt", "no raster")
    url = "https://portal.example/bad.zip"
    monkeypatch.setattr(
        static, "_settings", lambda: {"infomar_bathy": {"url": url, "licence": LIC}}
    )
    monkeypatch.setattr(static, "_download", lambda u, dest: shutil.copy(bad, dest))
    with pytest.raises(ValueError, match="one GeoTIFF"):
        static.fetch_bathy()
    assert not (raw / "manifest.json").exists()


def test_unconfigured_sources_stay_offline_stubs(raw, monkeypatch):
    monkeypatch.setattr(static, "_settings", dict)
    monkeypatch.setattr(
        static, "_download", lambda *a: pytest.fail("downloaded without a configured URL")
    )
    paths = [*static.fetch_inshore(), static.fetch_bathy()]
    assert {p.relative_to(raw).as_posix() for p in paths} == {
        "inshore/inshore_grounds.gpkg",
        "inshore/survey_extent.gpkg",
        "infomar_bathy.tif",
    }
    assert all(e["request"]["stub"] is True for e in _files(raw).values())
