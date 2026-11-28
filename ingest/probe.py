"""Friday go/no-go: one GFW presence query and one Sentinel-1 pass listing (ingest.s1.list_passes)."""

import os
from datetime import UTC, datetime, timedelta

from ingest import _stub, gfw, s1

_GFW_LAG_DAYS = 5  # A11: presence lags about 3 days, SAR and ERA5 about 5; a day this old has data
_S1_REPEAT_DAYS = 12  # one Sentinel-1 repeat cycle, so every relative orbit over the region appears


def probe() -> tuple[bool, bool, str]:
    """(s1_ok, gfw_ok, notes). Ok means the source answered with at least one pass or cell."""
    bbox = _stub.region()
    today = datetime.now(UTC).date()
    notes = []
    try:
        passes = s1.list_passes(bbox, today - timedelta(days=_S1_REPEAT_DAYS), today)
        s1_ok = len(passes) > 0
        notes.append(f"s1: {len(passes)} passes in the last {_S1_REPEAT_DAYS} days")
    except Exception as e:  # noqa: BLE001 -- a go/no-go reports every failure instead of raising
        s1_ok = False
        notes.append(f"s1 failed: {_safe(e)}")
    day = today - timedelta(days=_GFW_LAG_DAYS)
    try:
        rows = gfw._query(gfw._request(gfw.PRESENCE_DATASET, bbox, day, day, "DAILY", None))
        gfw_ok = len(rows) > 0
        notes.append(f"gfw: {len(rows)} presence cells on {day}")
    except Exception as e:  # noqa: BLE001
        gfw_ok = False
        notes.append(f"gfw failed: {_safe(e)}")
    return s1_ok, gfw_ok, "; ".join(notes)


def _safe(e: Exception) -> str:
    msg = f"{type(e).__name__}: {e}"
    token = os.environ.get("GFW_TOKEN")
    return msg.replace(token, "***") if token else msg
