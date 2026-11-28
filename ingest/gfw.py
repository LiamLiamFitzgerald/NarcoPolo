"""Global Fishing Watch 4Wings: SAR detections and AIS presence (gfw-api-python-client, token from GFW_TOKEN).

The client's 4Wings report is gridded (about 0.01 degree at HIGH): SAR comes as a detection count per cell
and hour, with no per-detection rows. That is the issue 1 fallback, so gfw_sar.parquet holds one row per
counted detection at its cell and hour, with scene_id null and length_m NaN.
Filter strings, vessel types, speed bins and chunk size come from config `gfw`; none is guessed (#212).
Every 4Wings request is cached on its own under raw/gfw/<key>.parquet, so an interrupted fetch resumes.
Our windows are inclusive; 4Wings' date-range end is exclusive (a one-day range start = end returns no rows,
checked on real data 28 Nov), so the day after `end` is sent.
"""

import asyncio
import os
from collections.abc import Iterator, Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.io import raw_root
from ingest import _stub
from ingest.cache import cached, record, request_key

LICENCE = (
    "Global Fishing Watch API data, CC BY-NC 4.0: non-commercial use only; "
    "attribution 'Powered by Global Fishing Watch'"
)
SAR_DATASET = "public-global-sar-presence:latest"
PRESENCE_DATASET = "public-global-presence:latest"
_METHOD = {
    SAR_DATASET: "create_sar_presence_report",
    PRESENCE_DATASET: "create_ais_presence_report",
}
_VALUE = {SAR_DATASET: "detections", PRESENCE_DATASET: "hours"}

_SAR = pa.schema(
    [
        ("scene_id", pa.large_string()), ("timestamp", pa.timestamp("ns", tz="UTC")),
        ("lon", pa.float64()), ("lat", pa.float64()), ("matched", pa.bool_()), ("length_m", pa.float64()),
    ]
)  # fmt: skip
_PRESENCE = pa.schema(
    [
        ("lon", pa.float64()), ("lat", pa.float64()), ("date", pa.date32()),
        ("speed_bin", pa.large_string()), ("vessel_type", pa.large_string()), ("hours", pa.float64()),
    ]
)  # fmt: skip


def fetch_sar(bbox: _stub.Bbox, start: date, end: date) -> Path:
    """raw/gfw_sar.parquet: one row per GFW SAR detection (gridded position and hour), matched and not."""
    s = _settings()
    matched = dict(s["sar_matched"])
    req = {
        "source": "gfw_sar",
        **_window(bbox, start, end),
        "matched": matched,
        "chunk": s["chunk_days"],
    }
    if (hit := cached(req)) is not None:
        return hit
    frames = [
        _query(_request(SAR_DATASET, bbox, a, b, "HOURLY", [flt])).assign(
            matched=str(label).lower() == "true"
        )
        for label, flt in matched.items()
        for a, b in _chunks(start, end, s["chunk_days"])
    ]
    df = pd.concat(frames, ignore_index=True)
    df = df.loc[df.index.repeat(df["detections"].astype("int64"))]  # a count of n becomes n rows
    out = pd.DataFrame(
        {
            "scene_id": None,  # not offered by the gridded report
            "timestamp": pd.to_datetime(df["date"], utc=True, format="ISO8601"),
            "lon": df["lon"],
            "lat": df["lat"],
            "matched": df["matched"],
            "length_m": float("nan"),  # not offered; never 0
        }
    )
    return _write(req, "gfw_sar.parquet", out, _SAR)


def fetch_presence(bbox: _stub.Bbox, start: date, end: date) -> Path:
    """raw/gfw_presence.parquet: daily AIS presence hours per finest-grid cell, vessel type and speed bin."""
    s = _settings()
    types, bins = dict(s["vessel_types"]), dict(s["speed_bins"])
    req = {
        "source": "gfw_presence", **_window(bbox, start, end),
        "vessel_types": types, "speed_bins": bins, "join": s["filter_join"], "chunk": s["chunk_days"],
    }  # fmt: skip
    if (hit := cached(req)) is not None:
        return hit
    frames = [
        _query(
            _request(PRESENCE_DATASET, bbox, a, b, "DAILY", [vf + s["filter_join"] + sf])
        ).assign(vessel_type=vt, speed_bin=sb)
        for vt, vf in types.items()
        for sb, sf in bins.items()
        for a, b in _chunks(start, end, s["chunk_days"])
    ]
    df = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame(
        {
            "lon": df["lon"],
            "lat": df["lat"],
            "date": pd.to_datetime(df["date"], format="ISO8601").dt.date,
            "speed_bin": df["speed_bin"],
            "vessel_type": df["vessel_type"],
            "hours": df["hours"],
        }
    )
    return _write(req, "gfw_presence.parquet", out, _PRESENCE)


def _settings() -> Mapping[str, Any]:
    s = _stub.config().get("gfw")
    if not s:
        raise KeyError(
            "config.yaml has no `gfw` block (filters, speed bins, chunk size); see issue #212"
        )
    return s


def _client() -> Any:
    token = os.environ["GFW_TOKEN"]  # KeyError names the variable, never a value
    import gfwapiclient  # lazy: not a project dependency yet (#213)

    return gfwapiclient.Client(access_token=token)


def _window(bbox: _stub.Bbox, start: date, end: date) -> dict:
    return {"bbox": [float(v) for v in bbox], "start": start.isoformat(), "end": end.isoformat()}


def _request(
    dataset: str, bbox: _stub.Bbox, start: date, end: date, temporal: str, filters: list[str] | None
) -> dict:
    """One 4Wings report request; the dict is also its cache key."""
    return {
        "source": "gfw_4wings", "dataset": dataset, **_window(bbox, start, end),
        "spatial_resolution": "HIGH", "temporal_resolution": temporal, "filters": filters,
    }  # fmt: skip


def _chunks(start: date, end: date, days: int | None) -> Iterator[tuple[date, date]]:
    """[start, end] cut at calendar multiples of `days` (inclusive ends), so a window that moves forward
    reuses every cached piece but its ends; one piece if days is unset."""
    if not days:
        yield start, end
        return
    while start <= end:
        stop = date.fromordinal((start.toordinal() // days + 1) * days - 1)
        yield start, min(stop, end)
        start = stop + timedelta(days=1)


def _query(req: dict) -> pd.DataFrame:
    """One cached 4Wings report: date, lat, lon and the value column, as returned; nothing else is kept."""
    if (hit := cached(req)) is not None:
        return pd.read_parquet(hit)
    lon0, lat0, lon1, lat1 = req["bbox"]
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    report = getattr(_client().fourwings, _METHOD[req["dataset"]])
    result = _run(
        report(
            spatial_resolution=req["spatial_resolution"],
            temporal_resolution=req["temporal_resolution"],
            filters=req["filters"],
            start_date=req["start"],
            end_date=(date.fromisoformat(req["end"]) + timedelta(days=1)).isoformat(),  # exclusive
            geojson={"type": "Polygon", "coordinates": [ring]},
        )
    )
    keep = ["date", "lat", "lon", _VALUE[req["dataset"]]]
    df = result.df(include=set(keep)).reindex(
        columns=keep
    )  # drops identity fields; empty keeps columns
    path = raw_root() / "gfw" / f"{request_key(req)}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    record(req, path, LICENCE)
    return df


def _run(coro: Any) -> Any:
    """Run one client call; the seam offline tests replace, as asyncio.run opens a local socket pair."""
    return asyncio.run(coro)


def _write(req: dict, rel: str, df: pd.DataFrame, schema: pa.Schema) -> Path:
    path = raw_root() / rel
    pq.write_table(pa.Table.from_pandas(df, schema=schema, preserve_index=False), path)
    record(req, path, LICENCE)
    return path
