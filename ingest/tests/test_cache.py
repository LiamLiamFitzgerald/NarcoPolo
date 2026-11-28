import hashlib
import json
import shutil

import pytest

import sim.simulate
from core import io
from core.config import load
from ingest import cache

REQ = {"product": "s1", "bbox": [-10.6, 51.1, -7.9, 51.95], "date": "2026-11-20"}
SEED = 20261127


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_RAW", str(tmp_path))
    return tmp_path


def _manifest(raw):
    return json.loads((raw / "manifest.json").read_text())


def _file(raw, name, data=b"x"):
    f = raw / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


def test_request_key_ignores_key_order():
    shuffled = {"date": "2026-11-20", "bbox": [-10.6, 51.1, -7.9, 51.95], "product": "s1"}
    assert cache.request_key(REQ) == cache.request_key(shuffled)
    assert len(cache.request_key(REQ)) == 64


def test_request_key_differs_on_any_value():
    assert cache.request_key(REQ) != cache.request_key({**REQ, "date": "2026-11-21"})


def test_cached_is_none_before_record(raw):
    assert cache.cached(REQ) is None


def test_record_then_cached_returns_path(raw):
    f = _file(raw, f"s1/{cache.request_key(REQ)}.tif")
    cache.record(REQ, f, "CC BY 4.0")
    assert cache.cached(REQ) == f
    assert cache.cached({**REQ, "date": "2026-11-21"}) is None


def test_manifest_entry_matches_simulator_fields(raw):
    f = _file(raw, "gfw_sar.parquet", b"abc")
    cache.record(REQ, f, "CC BY-NC 4.0")
    entry = _manifest(raw)["files"]["gfw_sar.parquet"]
    assert entry["request"] == REQ
    assert entry["sha256"] == hashlib.sha256(b"abc").hexdigest()
    assert entry["licence"] == "CC BY-NC 4.0"
    assert entry["download_time"].endswith("Z")


def test_record_again_replaces_entry(raw):
    f = _file(raw, "era5.nc")
    cache.record(REQ, f, "old")
    cache.record(REQ, f, "new")
    files = _manifest(raw)["files"]
    assert list(files) == ["era5.nc"]
    assert files["era5.nc"]["licence"] == "new"


def test_record_keeps_latest_dates(raw):
    latest = dict.fromkeys(("radar", "gfw_presence", "gfw_sar", "era5"), "2026-11-22")
    (raw / "manifest.json").write_text(json.dumps({"latest": latest, "files": {}}))
    cache.record(REQ, _file(raw, "era5.nc"), "lic")
    assert _manifest(raw)["latest"] == latest


def test_cached_is_none_when_file_deleted(raw):
    f = _file(raw, "era5.nc")
    cache.record(REQ, f, "lic")
    f.unlink()
    assert cache.cached(REQ) is None


def test_record_rejects_missing_licence(raw):
    with pytest.raises(ValueError):
        cache.record(REQ, _file(raw, "era5.nc"), "  ")


def test_record_rejects_file_outside_raw(raw, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere") / "x.tif"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        cache.record(REQ, outside, "lic")


def test_record_rejects_missing_file(raw):
    with pytest.raises(FileNotFoundError):
        cache.record(REQ, raw / "nope.tif", "lic")


def test_works_on_simulator_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    cfg = tmp_path / "config.yaml"
    shutil.copy(io.ROOT / "config.yaml", cfg)
    monkeypatch.setattr(io, "CONFIG_PATH", cfg)
    sim.simulate.simulate(load(cfg)[0], SEED)
    raw = tmp_path / "raw"
    before = _manifest(raw)

    hit = cache.cached({"simulated": True, "seed": SEED})
    assert hit is not None and hit.relative_to(raw).as_posix() in before["files"]

    cache.record(REQ, _file(raw, "extra.parquet"), "lic")
    after = _manifest(raw)
    assert after["latest"] == before["latest"]
    assert set(after["files"]) == set(before["files"]) | {"extra.parquet"}
