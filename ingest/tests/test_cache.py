import json

import pytest

from ingest import cache

REQ = {"product": "s1", "bbox": [-10.6, 51.1, -7.9, 51.95], "date": "2026-11-20"}


def test_request_key_ignores_key_order():
    shuffled = {
        "date": "2026-11-20",
        "bbox": [-10.6, 51.1, -7.9, 51.95],
        "product": "s1",
    }
    assert cache.request_key(REQ) == cache.request_key(shuffled)
    assert len(cache.request_key(REQ)) == 64


def test_request_key_differs_on_any_value():
    assert cache.request_key(REQ) != cache.request_key({**REQ, "date": "2026-11-21"})


def test_cached_is_none_before_record(tmp_path):
    assert cache.cached(REQ, raw_dir=tmp_path) is None


def test_record_then_cached_returns_path(tmp_path):
    f = tmp_path / "s1" / f"{cache.request_key(REQ)}.tif"
    f.parent.mkdir()
    f.write_bytes(b"x")
    cache.record(REQ, f, "CC BY 4.0", raw_dir=tmp_path)
    assert cache.cached(REQ, raw_dir=tmp_path) == f
    assert cache.cached({**REQ, "date": "2026-11-21"}, raw_dir=tmp_path) is None


def test_manifest_entry_has_request_hash_utc_time_and_licence(tmp_path):
    f = tmp_path / "gfw_sar.parquet"
    f.write_bytes(b"x")
    cache.record(REQ, f, "CC BY-NC 4.0", raw_dir=tmp_path)
    (entry,) = json.loads((tmp_path / "manifest.json").read_text())["files"]
    assert entry["path"] == "gfw_sar.parquet"
    assert entry["request"] == REQ
    assert entry["hash"] == cache.request_key(REQ)
    assert entry["licence"] == "CC BY-NC 4.0"
    assert entry["time_utc"].endswith("+00:00")


def test_record_appends(tmp_path):
    a, b = tmp_path / "a.nc", tmp_path / "b.nc"
    a.write_bytes(b"x")
    b.write_bytes(b"y")
    cache.record(REQ, a, "lic", raw_dir=tmp_path)
    cache.record({**REQ, "date": "2026-11-21"}, b, "lic", raw_dir=tmp_path)
    assert len(json.loads((tmp_path / "manifest.json").read_text())["files"]) == 2


def test_cached_is_none_when_file_deleted(tmp_path):
    f = tmp_path / "era5.nc"
    f.write_bytes(b"x")
    cache.record(REQ, f, "lic", raw_dir=tmp_path)
    f.unlink()
    assert cache.cached(REQ, raw_dir=tmp_path) is None


def test_record_rejects_missing_licence(tmp_path):
    f = tmp_path / "era5.nc"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        cache.record(REQ, f, "  ", raw_dir=tmp_path)


def test_record_rejects_file_outside_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    outside = tmp_path / "x.tif"
    outside.write_bytes(b"x")
    with pytest.raises(ValueError):
        cache.record(REQ, outside, "lic", raw_dir=raw)


def test_record_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        cache.record(REQ, tmp_path / "nope.tif", "lic", raw_dir=tmp_path)


def test_record_keeps_latest_dates(tmp_path):
    latest = {
        "radar": "2026-11-25",
        "gfw_presence": "2026-11-24",
        "gfw_sar": "2026-11-22",
        "era5": "2026-11-22",
    }
    (tmp_path / "manifest.json").write_text(json.dumps({"files": [], "latest": latest}))
    f = tmp_path / "era5.nc"
    f.write_bytes(b"x")
    cache.record(REQ, f, "lic", raw_dir=tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["latest"] == latest
    assert len(manifest["files"]) == 1
