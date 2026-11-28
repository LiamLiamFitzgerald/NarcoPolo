"""make fetch: every raw/ file for the region and windows in config; idempotent through the cache.

Order: ERA5 first (it picks the calm passes), then Sentinel-1 list -> select -> fetch, GFW, OSM, static.
Sentinel-1 scenes are fetched ingest.s1_workers at a time; a failed scene is retried once and never stops
the run. A rerun after a stop resumes: fetch_scene returns already-cached scenes without downloading.
Each source runs on its own: a failure is reported on stderr and the rest still run; FetchError at the end.
The window end (last full UTC day) is pinned in raw/manifest.json["window"] on the first fetch, so a rerun
on a later day sends the same requests and downloads nothing. Afterwards manifest["latest"] gets each
feed's latest date as found in the files (never guessed) and, once all four are known, data/snapshot.json.
"""

import json
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import netCDF4
import pandas as pd
import pyarrow.parquet as pq

from core import io
from core.config import Config
from core.io import raw_root
from ingest import _stub, era5, gfw, osm, s1, static

_FEEDS = ("radar", "gfw_presence", "gfw_sar", "era5")
S1_WORKERS = (
    2  # TODO(P2): config ingest.s1_workers = the openEO account's concurrent batch-job limit
)


class FetchError(RuntimeError):
    """One or more sources failed; every other source was still fetched."""


def fetch_all(config: Config) -> None:
    raw = raw_root()
    raw.mkdir(parents=True, exist_ok=True)
    bbox = _stub.region(config)
    pinned = _manifest(raw).get("window", {}).get("end")
    end = date.fromisoformat(pinned) if pinned else _today() - timedelta(days=1)
    ship_start = end - timedelta(days=config["ship_history_days"] - 1)
    radar_start = end - timedelta(days=config["radar_history_days"] - 1)
    # coverage's post_storm flag looks back storm_lookback_h before each pass (A9)
    lookback_days = -(-int(config["coverage"]["storm_lookback_h"]) // 24)
    era5_start = radar_start - timedelta(days=lookback_days)
    _say(
        f"window end {end} ({'pinned in manifest' if pinned else 'yesterday, UTC'}); "
        f"ship {ship_start}..{end}, radar {radar_start}..{end}, ERA5 {era5_start}..{end}"
    )
    _update_manifest(raw, window={"end": end.isoformat()})

    tally = {"downloaded": 0, "cached": 0}
    failed: list[str] = []

    def step(name: str, fn: Callable[[], Any]) -> Any:
        before = _manifest(raw)["files"] if (raw / "manifest.json").exists() else {}
        try:
            out = fn()
        except Exception as e:  # noqa: BLE001  # report and carry on: one source down must not stop the others
            failed.append(name)
            _say(f"FAILED {name}: {type(e).__name__}: {str(e)[:300]}")
            return None
        after = _manifest(raw)["files"]
        changed = {k for k, v in after.items() if before.get(k) != v}
        returned = {_rel(raw, p) for p in _paths(out)}
        size = lambda rel: (raw / rel).stat().st_size if (raw / rel).is_file() else 0
        for rel in sorted(returned):  # the files the fetcher hands back, one line each
            how = "downloaded" if rel in changed else "cached"
            tally[how] += 1
            _say(f"ok {name}: {how} {rel} {size(rel):,} B")
        if side := changed - returned:  # per-request caches and sidecars (raw/gfw/, scene .json)
            tally["downloaded"] += len(side)
            total = sum(size(rel) for rel in side)
            _say(f"ok {name}: downloaded {len(side):,} more files, {total:,} B")
        if not changed and not returned:
            _say(f"ok {name}")
        return out

    weather = step("era5", lambda: era5.fetch_era5(bbox, era5_start, end))
    if weather is None:
        _say("SKIPPED s1: needs era5 to choose the calm passes")
    else:
        passes = step("s1.list_passes", lambda: s1.list_passes(bbox, radar_start, end))
        chosen = (
            None
            if passes is None
            else step("s1.select_passes", lambda: s1.select_passes(passes, weather))
        )
        if chosen is not None:
            rows = [
                {str(k): v for k, v in r.items()}
                for r in chosen[chosen["downloaded"]].to_dict("records")
            ]
            workers = int(config.get("ingest", {}).get("s1_workers", S1_WORKERS))
            _say(f"s1: {len(rows)} of {len(chosen)} passes selected, {workers} at a time")
            _fetch_scenes(raw, rows, workers, tally, failed)
    step("gfw_sar", lambda: gfw.fetch_sar(bbox, ship_start, end))
    step("gfw_presence", lambda: gfw.fetch_presence(bbox, ship_start, end))
    step("osm.fetch_piers", lambda: osm.fetch_piers(bbox))
    step("osm.fetch_coastline", lambda: osm.fetch_coastline(bbox))
    step("static.fetch_inshore", static.fetch_inshore)
    step("static.fetch_bathy", static.fetch_bathy)

    latest = _latest(raw)
    manifest = _update_manifest(raw, latest=latest)
    if missing := [f for f in _FEEDS if f not in latest]:
        _say(f"latest {latest}; snapshot not written, no data yet for {missing}")
    else:
        io.stage_path("aggregate/observed").parent.parent.mkdir(parents=True, exist_ok=True)
        _say(f"latest {latest}; wrote {io.write_snapshot(manifest)}")
    _say(f"{tally['downloaded']} downloaded, {tally['cached']} cached, {len(failed)} failed")
    if failed:
        raise FetchError(f"failed: {', '.join(failed)}")


def _fetch_scenes(
    raw: Path, rows: list[dict], workers: int, tally: dict, failed: list[str]
) -> None:
    """fetch_scene for every row, `workers` in flight; each failure retried once, then reported."""
    before = set(_manifest(raw)["files"])  # a scene already here is a cache hit, not a download
    t0, done, total = time.monotonic(), 0, len(rows)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        tries: dict[Future, tuple[dict, int]] = {
            pool.submit(s1.fetch_scene, r): (r, 1) for r in rows
        }
        while tries:
            finished, _ = wait(tries, return_when=FIRST_COMPLETED)
            for fut in finished:
                row, attempt = tries.pop(fut)
                name = f"s1.fetch_scene:{row['pass_id']}"
                if (e := fut.exception()) is not None:
                    why = f"{type(e).__name__}: {str(e)[:300]}"
                    if attempt == 1:
                        _say(f"retry {name}: {why}")
                        tries[pool.submit(s1.fetch_scene, row)] = (row, 2)
                        continue
                    failed.append(name)
                    how = f"FAILED {name}: {why}"
                else:
                    rel = _rel(raw, fut.result())
                    kind = "cached" if rel in before else "downloaded"
                    tally[kind] += 1
                    size = (raw / rel).stat().st_size
                    how = f"{kind} {rel} {size:,} B"
                done += 1
                elapsed = timedelta(seconds=round(time.monotonic() - t0))
                _say(f"s1 {done}/{total} {how}, elapsed {elapsed}")


def _today() -> date:
    return datetime.now(UTC).date()


def _say(line: str) -> None:
    print(f"fetch: {line}", file=sys.stderr, flush=True)


def _paths(out: Any) -> list[Path]:
    if isinstance(out, Path):
        return [out]
    if isinstance(out, list | tuple):
        return [p for p in out if isinstance(p, Path)]
    return []


def _rel(raw: Path, path: Path) -> str:
    return path.resolve().relative_to(raw.resolve()).as_posix()


def _manifest(raw: Path) -> dict:
    path = raw / "manifest.json"
    if not path.exists():
        return {"files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _update_manifest(raw: Path, **top: Any) -> dict:
    """Set top-level keys (window, latest) beside ingest.cache's `files`; write-then-rename."""
    manifest = {**_manifest(raw), **top}
    tmp = raw / "manifest.json.tmp"
    tmp.write_text(
        json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, raw / "manifest.json")
    return manifest


def _latest(raw: Path) -> dict[str, str]:
    """Each feed's latest date from the downloaded files; a feed with no data has no key (never a guess)."""
    real = {
        rel for rel, e in _manifest(raw)["files"].items() if not e["request"].get("stub")
    }  # stub placeholders hold no data
    out: dict[str, date] = {}
    if "era5.nc" in real and (d := _era5_latest(raw / "era5.nc")) is not None:
        out["era5"] = d
    scenes = [
        pd.Timestamp(json.loads((raw / rel).read_text())["start_time"])
        for rel in real
        if rel.startswith("s1/") and rel.endswith(".json")
    ]
    if scenes:  # start times are UTC (spec Warnings); naive ones are taken as UTC, never local
        out["radar"] = max(
            t.tz_convert("UTC") if t.tz else t.tz_localize("UTC") for t in scenes
        ).date()
    for feed, column in (("gfw_sar", "timestamp"), ("gfw_presence", "date")):
        rel = f"{feed}.parquet"
        if rel in real:
            values = pq.read_table(raw / rel, columns=[column]).column(column).to_pandas()
            if len(values.dropna()):
                out[feed] = pd.Timestamp(values.max()).date()
    return {k: v.isoformat() for k, v in sorted(out.items())}


def _era5_latest(path: Path) -> date | None:
    """The last UTC day whose 24th hour is in the file (a part-delivered last day doesn't count)."""
    with netCDF4.Dataset(path) as nc:
        name = "valid_time" if "valid_time" in nc.variables else "time"
        t = nc.variables[name]
        if len(t) == 0:
            return None
        last: Any = netCDF4.num2date(t[:].max(), t.units, getattr(t, "calendar", "standard"))
    end = datetime(last.year, last.month, last.day, last.hour) + timedelta(hours=1)
    return (end - timedelta(days=1)).date()
