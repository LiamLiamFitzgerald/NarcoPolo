"""P5 aggregate: soft counts per 2 km cell, UTC date and event type, each paired with its exposure.

Dates are tz-naive pandas Timestamps at midnight, meaning the UTC date.
"""

import pandas as pd

from aggregate._stand_in import Observed, parent

EVENT_TYPES = ("dark_small", "slowdown")
_KEYS = ["cell_id", "date", "event_type"]


def _utc_date(times: pd.Series) -> pd.Series:
    t = pd.to_datetime(times, utc=True)
    return t.dt.tz_localize(None).dt.normalize()


def soft_counts(events: pd.DataFrame) -> pd.DataFrame:
    """C = sum of p per cell, UTC date and event type (principle 3: weak evidence adds up)."""
    e = events.assign(date=_utc_date(events["time_utc"]))
    return e.groupby(_KEYS, as_index=False)["p"].sum().rename(columns={"p": "count"})


def exposure_rows(
    exposure: pd.DataFrame,
    cells: pd.DataFrame,
    dates: pd.DatetimeIndex,
    slowdown_last_date: pd.Timestamp,
) -> pd.DataFrame:
    """Exposure E for every 2 km cell, date and event type, zeros included.

    dark_small: sum of exposure_small over that day's passes (rough passes already carry 0).
    slowdown: the cell's sea_frac per day, and 0 after GFW presence's latest date (A11).
    """
    fine = cells.loc[cells["level"] == 2000, ["cell_id", "sea_frac"]]
    grid = fine.merge(pd.DataFrame({"date": dates}), how="cross")

    passes = exposure.assign(date=_utc_date(exposure["time_utc"]))
    small = passes.groupby(["cell_id", "date"], as_index=False)["exposure_small"].sum()
    small = grid[["cell_id", "date"]].merge(small, on=["cell_id", "date"], how="left")
    small = small.assign(
        event_type="dark_small", exposure=small["exposure_small"].fillna(0.0)
    )

    slow = grid.assign(
        event_type="slowdown",
        exposure=grid["sea_frac"].where(grid["date"] <= slowdown_last_date, 0.0),
    )
    cols = [*_KEYS, "exposure"]
    return pd.concat([small[cols], slow[cols]], ignore_index=True)


def build_observed(counts: pd.DataFrame, exposure: pd.DataFrame) -> Observed:
    """Full grid at 2 km: every (cell, date, type) row, E = 0 rows kept with C = 0."""
    frame = exposure.merge(counts, on=_KEYS, how="left")
    frame["count"] = frame["count"].fillna(0.0)
    frame["level"] = 2000
    return Observed(frame)  # raises if an event landed where we never looked


def run(
    events: pd.DataFrame,
    exposure: pd.DataFrame,
    cells: pd.DataFrame,
    dates: pd.DatetimeIndex,
    slowdown_last_date: pd.Timestamp,
) -> Observed:
    """The whole aggregate stage: 2 km rows plus their 10 km roll-up, both event types.

    shortcut: returns the frame; once core/io exists this writes aggregate/observed.parquet.
    """
    fine = build_observed(
        soft_counts(events), exposure_rows(exposure, cells, dates, slowdown_last_date)
    )
    return Observed(pd.concat([fine.frame, to_coarse(fine).frame], ignore_index=True))


def to_coarse(observed: Observed) -> Observed:
    """10 km cells: sum C and E over the 25 children."""
    f = observed.frame.assign(cell_id=observed.frame["cell_id"].map(parent))
    coarse = f.groupby(_KEYS, as_index=False)[["count", "exposure"]].sum()
    return Observed(coarse.assign(level=10000))
