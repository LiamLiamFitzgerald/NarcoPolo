"""Only timezone-aware UTC timestamps. A naive timestamp is a bug, so it raises."""

from datetime import date

import pandas as pd


def utc(ts: object) -> pd.Timestamp:
    t = pd.Timestamp(ts)  # pyright: ignore[reportArgumentType]
    if t.tzinfo is None:
        raise ValueError(f"naive timestamp {ts!r}: attach a timezone first")
    return t.tz_convert("UTC")


def utc_date(ts: object) -> date:
    return utc(ts).date()


def iso_week(d: date) -> tuple[int, int]:
    y, w, _ = d.isocalendar()
    return y, w
