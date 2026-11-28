"""Every offline stub (era5, osm, gfw are real; static is real once its URLs are configured: tests/test_*.py) writes the raw/ shape the simulator writes, records it with a licence, and opens no socket."""

import json
import socket
import struct
from datetime import date

import pyogrio
import pytest

from ingest import static
from ingest.tests.conftest import CFG

B = CFG["region_bbox"]
BBOX = (B["lon_min"], B["lat_min"], B["lon_max"], B["lat_max"])
START, END = date(2026, 11, 1), date(2026, 11, 3)


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("stub opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    return tmp_path


def _files(raw):
    return json.loads((raw / "manifest.json").read_text())["files"]


def _recorded(raw, path):
    entry = _files(raw)[path.relative_to(raw).as_posix()]
    assert entry["licence"].strip() and entry["request"]["stub"] is True


def _tiff_tags(path):
    """{tag: values} from the first IFD of a little-endian TIFF."""
    b = path.read_bytes()
    (ifd,) = struct.unpack_from("<I", b, 4)
    (n,) = struct.unpack_from("<H", b, ifd)
    fmt, size, tags = {3: "H", 4: "I", 12: "d"}, {3: 2, 4: 4, 12: 8}, {}
    for i in range(n):
        tag, typ, count = struct.unpack_from("<HHI", b, ifd + 2 + 12 * i)
        at = ifd + 2 + 12 * i + 8
        if size[typ] * count > 4:
            (at,) = struct.unpack_from("<I", b, at)
        tags[tag] = list(struct.unpack_from(f"<{count}{fmt[typ]}", b, at))
    return tags


def _same_raster_shape(stub, simulated):
    a, s = _tiff_tags(stub), _tiff_tags(simulated)
    for tag in (258, 339, 34735):  # bits per band, sample format, GeoKeys (EPSG:32629)
        assert a[tag] == s[tag], tag
    assert a.get(277, [1]) == s.get(277, [1])  # band count


def _same_gpkg_shape(stub, simulated, layer):
    a, s = pyogrio.read_info(stub, layer=layer), pyogrio.read_info(simulated, layer=layer)
    assert a["geometry_type"] == s["geometry_type"] and a["crs"] == s["crs"]
    assert list(a["fields"]) == list(s["fields"]) and a["features"] == 0


def test_fetch_inshore_matches_simulator(simraw, raw):
    paths = static.fetch_inshore()
    assert {p.relative_to(raw).as_posix() for p in paths} == {
        p.relative_to(simraw).as_posix() for p in (simraw / "inshore").glob("*.gpkg")
    }
    for p in paths:
        _same_gpkg_shape(p, simraw / "inshore" / p.name, p.stem)
        _recorded(raw, p)


def test_fetch_bathy_matches_simulator(simraw, raw):
    path = static.fetch_bathy()
    _same_raster_shape(path, simraw / "infomar_bathy.tif")
    _recorded(raw, path)
