"""Global Fishing Watch 4Wings: SAR detections and AIS presence (gfw-api-python-client, token from GFW_TOKEN)."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ingest import _stub

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


def _empty(schema: pa.Schema) -> Callable[[Path], None]:
    return lambda path: pq.write_table(schema.empty_table(), path)


def fetch_sar(bbox: _stub.Bbox, start: date, end: date) -> Path:
    """raw/gfw_sar.parquet. Stub: no rows (nothing downloaded), columns as the simulator writes them."""
    req = _stub.request("gfw_sar", bbox, start, end)
    return _stub.get(req, "gfw_sar.parquet", _empty(_SAR))


def fetch_presence(bbox: _stub.Bbox, start: date, end: date) -> Path:
    """raw/gfw_presence.parquet: daily, finest grid, with vessel_type and speed_bin. Stub: no rows."""
    req = _stub.request("gfw_presence", bbox, start, end)
    return _stub.get(req, "gfw_presence.parquet", _empty(_PRESENCE))
