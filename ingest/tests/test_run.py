"""fetch_all with every fetcher mocked: order, idempotence, one failing source, manifest `latest`, snapshot."""

import json
import socket
import threading
import time
from datetime import date, timedelta
from typing import Any

import netCDF4
import numpy as np
import pandas as pd
import pytest

from core import io
from ingest import era5, gfw, osm, run, s1, static
from ingest.cache import cached, record
from ingest.tests.conftest import CFG, FakeCDS

END = date(2026, 11, 20)
LICENCE = "test licence"


@pytest.fixture(autouse=True)
def raw(tmp_path, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("opened a socket")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("NARCO_RAW", str(tmp_path / "raw"))
    monkeypatch.setenv("NARCO_DATA", str(tmp_path / "data"))
    (tmp_path / "raw").mkdir()
    (tmp_path / "data").mkdir()
    return tmp_path / "raw"


class Fakes:
    """Every fetcher replaced by one that writes a small real-looking file through ingest.cache.
    `calls` is the order fetchers were called; `downloads` the files actually written."""

    def __init__(self, raw):
        self.raw, self.calls, self.downloads, self.fail = raw, [], [], set()
        self.passes = pd.DataFrame(
            {
                "pass_id": ["a", "b", "c"],
                "time": pd.to_datetime(
                    ["2026-11-10T06:20Z", "2026-11-14T18:10Z", "2026-11-18T06:30Z"], utc=True
                ),
                "orbit_dir": ["DESCENDING", "ASCENDING", "DESCENDING"],
                "rel_orbit": [1, 2, 1],
                "footprint": ["POLYGON EMPTY"] * 3,
            }
        )

    def _get(self, name, req, rel, write):
        self.calls.append(name)
        if name in self.fail:
            raise RuntimeError(f"{name} is down")
        if (hit := cached(req)) is not None:
            return hit
        path = self.raw / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path)
        record(req, path, LICENCE)
        self.downloads.append(rel)
        return path

    def era5(self, bbox, start, end):
        def write(path):
            hours = pd.date_range(start, end + timedelta(days=1), freq="h", inclusive="left")
            with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
                nc.createDimension("time", len(hours))
                t = nc.createVariable("time", "i4", ("time",))
                t.units = "hours since 1900-01-01 00:00:00.0"
                t[:] = netCDF4.date2num(hours.to_pydatetime(), t.units)

        req = {"source": "era5", "start": start.isoformat(), "end": end.isoformat()}
        return self._get("era5", req, "era5.nc", write)

    def list_passes(self, bbox, start, end):
        self.calls.append("s1.list_passes")
        if "s1.list_passes" in self.fail:
            raise RuntimeError("catalogue is down")
        self.radar_window = (start, end)
        return self.passes

    def select_passes(self, passes, era5_path):
        self.calls.append("s1.select_passes")
        assert era5_path == self.raw / "era5.nc"  # the calm passes are picked from ERA5
        return passes.assign(downloaded=passes["pass_id"] != "b")

    def fetch_scene(self, row):
        def write(path):
            path.write_bytes(b"II*\x00")
            meta = {"pass_id": row["pass_id"], "start_time": pd.Timestamp(row["time"]).isoformat()}
            meta_path = path.with_suffix(".json")
            meta_path.write_text(json.dumps(meta))
            record(
                {"source": "s1", "pass_id": row["pass_id"], "part": "metadata"}, meta_path, LICENCE
            )

        req = {"source": "s1", "pass_id": row["pass_id"]}
        return self._get(f"s1.fetch_scene:{row['pass_id']}", req, f"s1/{row['pass_id']}.tif", write)

    def _parquet(self, name, frame):
        def fetch(bbox, start, end):
            req = {"source": name, "start": start.isoformat(), "end": end.isoformat()}
            return self._get(name, req, f"{name}.parquet", lambda p: frame.to_parquet(p))

        return fetch

    def _static(self, name, rel):
        return lambda *a: self._get(name, {"source": name}, rel, lambda p: p.write_bytes(b"x"))

    def install(self, monkeypatch):
        sar = pd.DataFrame(
            {"timestamp": pd.to_datetime(["2026-11-12T06:00Z", "2026-11-15T18:00Z"])}
        )
        presence = pd.DataFrame(
            {"date": [date(2026, 11, 16), date(2026, 11, 17)], "hours": [1.0, 2.0]}
        )
        for mod, attr, fn in (
            (era5, "fetch_era5", self.era5),
            (s1, "list_passes", self.list_passes),
            (s1, "select_passes", self.select_passes),
            (s1, "fetch_scene", self.fetch_scene),
            (gfw, "fetch_sar", self._parquet("gfw_sar", sar)),
            (gfw, "fetch_presence", self._parquet("gfw_presence", presence)),
            (osm, "fetch_piers", self._static("osm.fetch_piers", "osm_piers.geojson")),
            (osm, "fetch_coastline", self._static("osm.fetch_coastline", "coastline.gpkg")),
            (static, "fetch_bathy", self._static("static.fetch_bathy", "infomar_bathy.tif")),
        ):
            monkeypatch.setattr(mod, attr, fn)
        monkeypatch.setattr(
            static,
            "fetch_inshore",
            lambda: [self._static("static.fetch_inshore", "inshore/net.gpkg")()],
        )
        return self


@pytest.fixture
def fakes(raw, monkeypatch):
    monkeypatch.setattr(run, "_today", lambda: END + timedelta(days=1))  # end = yesterday, UTC
    return Fakes(raw).install(monkeypatch)


def _manifest(raw):
    return json.loads((raw / "manifest.json").read_text())


def test_order_era5_first_then_s1_gfw_osm_static(fakes):
    run.fetch_all(CFG)
    assert fakes.calls == [
        "era5",
        "s1.list_passes",
        "s1.select_passes",
        *sorted(_scene_calls(fakes)),  # in parallel, so in any order
        "gfw_sar",
        "gfw_presence",
        "osm.fetch_piers",
        "osm.fetch_coastline",
        "static.fetch_inshore",
        "static.fetch_bathy",
    ]
    assert sorted(_scene_calls(fakes)) == ["s1.fetch_scene:a", "s1.fetch_scene:c"]  # selected only
    radar_days = CFG["radar_history_days"]
    assert fakes.radar_window == (END - timedelta(days=radar_days - 1), END)


def test_windows_count_back_from_end(fakes, raw):
    run.fetch_all(CFG)
    req = {e["request"]["source"]: e["request"] for e in _manifest(raw)["files"].values()}
    ship_start = END - timedelta(days=CFG["ship_history_days"] - 1)
    assert req["gfw_presence"]["start"] == req["gfw_sar"]["start"] == ship_start.isoformat()
    assert req["gfw_presence"]["end"] == END.isoformat()
    # ERA5 covers the radar window plus coverage's storm look-back before its first pass
    lookback = -(-CFG["coverage"]["storm_lookback_h"] // 24)
    radar_start = END - timedelta(days=CFG["radar_history_days"] - 1)
    assert req["era5"]["start"] == (radar_start - timedelta(days=lookback)).isoformat()
    assert req["era5"]["end"] == END.isoformat()


def test_second_fetch_all_downloads_nothing(fakes, raw):
    run.fetch_all(CFG)
    first, n = _manifest(raw), len(fakes.downloads)
    assert n == 9  # era5, scenes a and c, two gfw, two osm, inshore, bathy
    run.fetch_all(CFG)
    assert len(fakes.downloads) == n and _manifest(raw) == first


def test_end_is_pinned_so_a_later_day_still_downloads_nothing(fakes, raw, monkeypatch):
    run.fetch_all(CFG)
    n = len(fakes.downloads)
    assert _manifest(raw)["window"] == {"end": END.isoformat()}
    monkeypatch.setattr(run, "_today", lambda: END + timedelta(days=3))
    run.fetch_all(CFG)
    assert len(fakes.downloads) == n and _manifest(raw)["window"] == {"end": END.isoformat()}


def test_every_raw_file_is_in_the_manifest_with_a_licence(fakes, raw):
    run.fetch_all(CFG)
    on_disk = {p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file()}
    files = _manifest(raw)["files"]
    assert on_disk - {"manifest.json"} == set(files)
    assert all(e["licence"].strip() for e in files.values())


def test_latest_dates_and_snapshot(fakes, raw):
    run.fetch_all(CFG)
    assert _manifest(raw)["latest"] == {
        "era5": END.isoformat(),  # last full UTC day of hours
        "radar": "2026-11-18",  # latest downloaded scene, not latest listed pass
        "gfw_sar": "2026-11-15",
        "gfw_presence": "2026-11-17",
    }
    snap = io.read_snapshot()
    assert snap["T"] == date(2026, 11, 15)  # the earliest of the four (A11)


def test_era5_latest_is_the_last_full_utc_day(tmp_path):
    path = tmp_path / "partial.nc"
    with netCDF4.Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        nc.createDimension("time", 36)  # one full day and half the next
        t = nc.createVariable("time", "i4", ("time",))
        t.units = "hours since 2026-11-01 00:00:00"
        t[:] = np.arange(36)
    assert run._era5_latest(path) == date(2026, 11, 1)


@pytest.mark.parametrize("down", ["gfw_presence", "era5", "s1.list_passes", "s1.fetch_scene:a"])
def test_a_failing_source_is_reported_and_the_rest_still_run(fakes, raw, down, capsys):
    fakes.fail.add(down)
    with pytest.raises(run.FetchError) as err:
        run.fetch_all(CFG)
    assert down in str(err.value)
    report = capsys.readouterr().err
    assert f"FAILED {down}" in report
    assert "static.fetch_bathy" in fakes.calls  # the last source still ran
    assert "infomar_bathy.tif" in _manifest(raw)["files"]
    if down == "era5":  # no weather, so no calm passes to choose
        assert not any(c.startswith("s1.") for c in fakes.calls)
        assert "SKIPPED s1" in report
    if down == "s1.fetch_scene:a":
        assert "s1.fetch_scene:c" in fakes.calls  # one bad scene doesn't stop the next
    if down in ("gfw_presence", "era5"):
        assert down not in _manifest(raw)["latest"]  # never a guessed date
        assert not (io.stage_path("aggregate/observed").parent.parent / "snapshot.json").exists()


def test_report_names_every_file_with_size(fakes, capsys):
    run.fetch_all(CFG)
    report = capsys.readouterr().err
    assert "downloaded" in report and "era5.nc" in report and " B" in report
    run.fetch_all(CFG)
    report = capsys.readouterr().err
    assert "downloaded" not in report.replace("0 downloaded", "") and "cached" in report


def test_real_fetchers_with_offline_fakes(simraw, raw, monkeypatch, fake_gfw):
    """The real era5/osm/gfw modules behind fake CDS, Overpass and GFW clients; s1 and static as merged."""
    with netCDF4.Dataset(simraw / "era5.nc") as s:
        last: Any = netCDF4.num2date(s["time"][:].max(), s["time"].units)
    end = date(last.year, last.month, last.day)
    cds = FakeCDS(simraw / "era5.nc")
    monkeypatch.setattr(era5, "_client", lambda: cds)
    monkeypatch.setattr(osm, "_overpass", lambda q: {"elements": []})
    monkeypatch.setattr(run, "_today", lambda: end + timedelta(days=1))
    small = {**CFG, "ship_history_days": 3}  # keep the fake GFW call count small
    run.fetch_all(small)
    files, n_cds, n_gfw = _manifest(raw)["files"], len(cds.calls), len(fake_gfw)
    on_disk = {p.relative_to(raw).as_posix() for p in raw.rglob("*") if p.is_file()}
    assert on_disk - {"manifest.json"} == set(files)
    assert {"era5.nc", "gfw_sar.parquet", "gfw_presence.parquet", "coastline.gpkg"} <= set(files)
    assert all(e["licence"].strip() for e in files.values())
    run.fetch_all(small)
    assert _manifest(raw)["files"] == files and (len(cds.calls), len(fake_gfw)) == (n_cds, n_gfw)


# --- Sentinel-1 scenes: N in flight, resume, retry once (#33) ---


def _many(fakes, n):
    """n selected passes instead of the three in Fakes."""
    fakes.passes = pd.DataFrame(
        {
            "pass_id": [f"p{i:02d}" for i in range(n)],
            "time": pd.date_range("2026-11-01T06:20Z", periods=n, freq="12h"),
            "orbit_dir": ["DESCENDING"] * n,
            "rel_orbit": [1] * n,
            "footprint": ["POLYGON EMPTY"] * n,
        }
    )
    fakes.select_passes = lambda passes, era5_path: passes.assign(downloaded=True)
    return fakes


def _workers(n):
    return {**CFG, "ingest": {**CFG["ingest"], "s1_workers": n}}


def _scene_calls(fakes):
    return [c for c in fakes.calls if c.startswith("s1.fetch_scene:")]


def test_scenes_run_n_at_once_and_never_more(fakes, monkeypatch):
    _many(fakes, 7).install(monkeypatch)
    real, lock = fakes.fetch_scene, threading.Lock()
    now = {"in": 0, "max": 0}
    three = threading.Barrier(3, timeout=10)  # passes only if 3 scenes are in flight together

    def slow(row):
        with lock:
            now["in"] += 1
            now["max"] = max(now["max"], now["in"])
        if row["pass_id"] in ("p00", "p01", "p02"):
            three.wait()
        time.sleep(0.02)
        with lock:
            now["in"] -= 1
        return real(row)

    monkeypatch.setattr(s1, "fetch_scene", slow)
    run.fetch_all(_workers(3))
    assert now["max"] == 3
    assert sorted(_scene_calls(fakes)) == [f"s1.fetch_scene:p{i:02d}" for i in range(7)]


def test_parallel_scenes_all_reach_the_manifest(fakes, raw, monkeypatch):
    _many(fakes, 12).install(monkeypatch)
    run.fetch_all(_workers(6))  # 6 threads writing manifest.json at once
    files = _manifest(raw)["files"]
    assert {f"s1/p{i:02d}.tif" for i in range(12)} <= set(files)
    assert {f"s1/p{i:02d}.json" for i in range(12)} <= set(files)


def test_one_progress_line_per_finished_pass(fakes, monkeypatch, capsys):
    _many(fakes, 4).install(monkeypatch)
    run.fetch_all(_workers(2))
    lines = [ln for ln in capsys.readouterr().err.splitlines() if "fetch: s1 " in ln and "/4" in ln]
    assert sorted(ln.split("s1 ")[1].split(" ")[0] for ln in lines) == ["1/4", "2/4", "3/4", "4/4"]
    assert all("elapsed" in ln and "downloaded" in ln for ln in lines)


def test_a_pass_that_fails_once_is_retried_and_counts_as_done(fakes, raw, monkeypatch, capsys):
    _many(fakes, 3).install(monkeypatch)
    real, tries = fakes.fetch_scene, {"p01": 0}

    def flaky(row):
        if row["pass_id"] == "p01" and tries["p01"] == 0:
            tries["p01"] += 1
            raise TimeoutError("openEO batch job timed out")
        return real(row)

    monkeypatch.setattr(s1, "fetch_scene", flaky)
    run.fetch_all(_workers(2))  # no FetchError: the retry worked
    report = capsys.readouterr().err
    assert "retry s1.fetch_scene:p01" in report and "TimeoutError" in report
    assert "s1/p01.tif" in _manifest(raw)["files"]


def test_a_pass_that_fails_twice_is_reported_and_the_rest_finish(fakes, raw, monkeypatch, capsys):
    _many(fakes, 4).install(monkeypatch)
    fakes.fail.add("s1.fetch_scene:p02")
    with pytest.raises(run.FetchError, match="s1.fetch_scene:p02"):
        run.fetch_all(_workers(2))
    report = capsys.readouterr().err
    assert _scene_calls(fakes).count("s1.fetch_scene:p02") == 2  # tried, retried once, no more
    assert "FAILED s1.fetch_scene:p02: RuntimeError: s1.fetch_scene:p02 is down" in report
    assert {"s1/p00.tif", "s1/p01.tif", "s1/p03.tif"} <= set(_manifest(raw)["files"])
    assert "static.fetch_bathy" in fakes.calls


def test_resume_after_a_stop_fetches_only_what_is_missing(fakes, raw, monkeypatch, capsys):
    _many(fakes, 5).install(monkeypatch)
    fakes.fail.update({"s1.fetch_scene:p01", "s1.fetch_scene:p03"})  # stopped before these landed
    with pytest.raises(run.FetchError):
        run.fetch_all(_workers(2))
    done = set(fakes.downloads)
    fakes.fail.clear()
    capsys.readouterr()
    run.fetch_all(_workers(2))
    assert set(fakes.downloads) - done == {"s1/p01.tif", "s1/p03.tif"}
    report = capsys.readouterr().err
    assert report.count("cached s1/") == 3 and report.count("downloaded s1/") == 2


def test_a_pass_listed_twice_is_fetched_once(fakes, monkeypatch):
    _many(fakes, 3)
    fakes.passes = pd.concat([fakes.passes, fakes.passes.iloc[[1]]], ignore_index=True)
    fakes.install(monkeypatch)
    run.fetch_all(_workers(3))  # two threads on one pass would both miss the cache
    assert sorted(_scene_calls(fakes)) == [f"s1.fetch_scene:p{i:02d}" for i in range(3)]
