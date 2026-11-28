"""One pandera schema per stage file (docs/shared.md, Data dictionary). Extra columns are rejected, so a raw
ship identifier cannot slip into a file after match/. Cross-file rules (every cell_id exists in the cells layer)
and the config hash / seed stamp are checked by core.io, not here."""

import numbers
import re
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd
import pandera.pandas as pa


def _id() -> pa.Column:
    """A string key (#171): a numeric pass_id would validate, then never join with the string ones."""
    # plain Python, so any storage dtype works, including an empty pandas string column (an Arrow-backed
    # .all() raises on string dtype); empty is fine
    ok = lambda s: all(isinstance(v, str) for v in s)
    return pa.Column(checks=pa.Check(ok, error="not a string id"), nullable=False)


def _num(
    dtype: type | str = float,
    nullable: bool = False,
    *,
    ge: float | None = None,
    le: float | None = None,
) -> pa.Column:
    checks = [pa.Check.ge(ge)] if ge is not None else []
    checks += [pa.Check.le(le)] if le is not None else []
    return pa.Column(dtype, checks, nullable=nullable, coerce=True)


def _prob(nullable: bool = False) -> pa.Column:  # a probability or fraction
    return _num(float, nullable, ge=0, le=1)


def _utc() -> pa.Column:
    ok = lambda s: isinstance(s.dtype, pd.DatetimeTZDtype) and str(s.dtype.tz) == "UTC"
    return pa.Column(checks=pa.Check(ok, error="not timezone-aware UTC"), nullable=False)


def _is_date(s: pd.Series) -> bool:
    """Calendar dates (#171): parseable, timezone-naive and at midnight, so merges on date never drop rows."""
    d = pd.to_datetime(s, errors="coerce")
    if isinstance(d.dtype, pd.DatetimeTZDtype):
        return False
    return bool(d.notna().all() and (d == d.dt.normalize()).all())


def _date(nullable: bool = False) -> pa.Column:
    ok = (lambda s: _is_date(s.dropna())) if nullable else _is_date
    return pa.Column(
        checks=pa.Check(ok, element_wise=False, error="not calendar dates (naive, midnight)"),
        nullable=nullable,
    )


def _flag() -> pa.Column:
    return pa.Column(bool, nullable=False)


def _flag_or_na() -> pa.Column:
    """True / False / NA, stored as pandas' nullable "boolean": unknown is never "no" (principle 4)."""
    return pa.Column("boolean", nullable=True, coerce=True)


def _in(*values: object) -> pa.Column:
    return pa.Column(checks=pa.Check.isin(list(values)), nullable=False)


def _str_list() -> pa.Column:
    ok = lambda s: all(
        isinstance(v, list | tuple | np.ndarray) and all(isinstance(i, str) for i in v) for v in s
    )
    return pa.Column(checks=pa.Check(ok, error="not a list of str"), nullable=False)


def _float_list(ge: float | None = None) -> pa.Column:
    """A list of real numbers (ints welcome, bools and NaN refused when ge is set) per row."""
    num = lambda i: isinstance(i, numbers.Real) and not isinstance(i, bool | np.bool_)
    ok = lambda s: all(
        isinstance(v, list | tuple | np.ndarray)
        and all(num(i) and (ge is None or i >= ge) for i in v)
        for v in s
    )
    return pa.Column(checks=pa.Check(ok, error="not a list of numbers"), nullable=False)


def _same_length(a: str, b: str) -> pa.Check:
    """When column b is present, each row's list b is as long as its list a."""
    return pa.Check(
        lambda df: (
            df[a].map(len) == df[b].map(len) if b in df.columns else pd.Series(True, df.index)
        ),
        error=f"len({b}) != len({a})",
    )


def _later(col: pa.Column) -> pa.Column:
    """A column the learning layer adds (docs/learning.md): checked when present, not yet required."""
    col.required = False
    return col


def _unique(*cols: str) -> pa.Check:
    return pa.Check(
        lambda df: ~df.duplicated(list(cols)), error=f"duplicate ({', '.join(cols)}) rows"
    )


def _schema(columns: dict[str, pa.Column], *checks: pa.Check) -> pa.DataFrameSchema:
    return pa.DataFrameSchema(columns, checks=list(checks), strict=True, ordered=False)


_event_type = _in(
    "dark_small", "dark_medium", "slowdown"
)  # dark_medium: unmatched medium-size boats (#344)
_count_needs_exposure = pa.Check(
    lambda df: ~((df["count"] > 0) & (df["exposure"] <= 0)), error="count > 0 where exposure = 0"
)

SCHEMAS: dict[str, pa.DataFrameSchema] = {
    "reference/cells": _schema(
        {  # the cells layer of reference/layers.gpkg
            "cell_id": pa.Column(str, nullable=False),
            "level": _in(2000, 10000),
            "geometry": pa.Column(nullable=False),
            "inshore_frac": _prob(nullable=True),  # NaN where no inshore map exists
            "lane": _flag(),
            "anchorage": _flag(),
            "port_zone": _flag(),
            "exclusion": _flag(),
            "dist_coast_m": _num(ge=0),
            "static_frac": _prob(),
            "sea_frac": _num(ge=0.2, le=1),
        }
    ),
    "reference/piers": _schema(
        {  # the piers layer of reference/layers.gpkg
            "pier_id": pa.Column(str, nullable=False),
            "name": pa.Column(str, nullable=True),
            "geometry": pa.Column(nullable=False),
            "road_access": _flag(),
        }
    ),
    "reference/land": _schema(
        {  # the land layer of reference/layers.gpkg (#133): one (multi)polygon, for the basemap
            "id": pa.Column(int, nullable=False),
            "geometry": pa.Column(nullable=False),
        }
    ),
    "reference/closed_areas": _schema(
        {  # #322: the closed_areas layer of reference/layers.gpkg (P3 writes, P6 and P7 read); EPSG:32629
            "area_id": _id(),
            "name": pa.Column(
                str, nullable=False
            ),  # the published area name; never a person's name
            "type": _in("closure", "protected_area"),
            "start_date": _date(
                nullable=True
            ),  # UTC calendar dates where published; NaT = no date given
            "end_date": _date(nullable=True),
            "geometry": pa.Column(nullable=False),
        },
        pa.Check(
            lambda df: ~(pd.to_datetime(df["start_date"]) > pd.to_datetime(df["end_date"])),
            error="start_date > end_date",
        ),
    ),
    "reference/travel_hours": _schema(
        {
            "cell_id": pa.Column(str, nullable=False),
            "pier_id": pa.Column(str, nullable=False),
            "hours": _num(ge=0),
        }
    ),
    "reference/presence_2km": _schema(  # #208: reference.regrid_presence output (shared.md issue 4)
        {
            "cell_id": pa.Column(str, nullable=False),
            "date": _date(),  # UTC
            "vessel_type": pa.Column(str, nullable=False),  # as in raw/gfw_presence
            "speed_bin": pa.Column(str, nullable=False),  # GFW's label, e.g. "0-2", "8+"
            "hours": _num(ge=0),  # area-weighted presence hours
        },
        _unique("cell_id", "date", "vessel_type", "speed_bin"),
    ),
    "coverage/weather_daily": _schema(  # #208: max over the UTC day's hourly ERA5, coverage.weather_at point rules
        {
            "cell_id": pa.Column(str, nullable=False),
            "date": _date(),  # UTC
            "wind_max_ms": _num(ge=0),
            "hs_max_m": _num(ge=0),  # no row where ERA5 is unknown: never 0 or NaN in its place
        },
        _unique("cell_id", "date"),
    ),
    "validate/pboat_training": _schema(  # #209: labelled injection-run candidates; P4's fit_pboat trains on them
        {
            "pass_id": _id(),
            "cell_id": pa.Column(
                str, nullable=False
            ),  # with pass_id, P4 joins wind_ms from coverage/exposure
            "date": _date(),  # the chip's UTC date: core.Split drops rows after the cut-off
            "peak_ratio_vv_db": _num(),
            "peak_ratio_vh_db": _num(),
            "pol_agree": _flag(),
            "n_px": _num(int, ge=1),
            "ghost": _flag(),
            "label": _flag(),  # True at an injected boat; False > pboat_negative_m from any injection or AIS ship
        }
    ),
    "coverage/exposure": _schema(
        {
            "cell_id": pa.Column(str, nullable=False),
            "pass_id": _id(),
            "time_utc": _utc(),
            "covered_frac": _prob(),
            "wind_ms": _num(ge=0),
            "hs_m": _num(ge=0),
            "calm": _flag(),
            "exposure_small": _prob(),
            "post_storm": _flag(),  # A9: >= 24 h of hs > 2.5 m in the 72 h before the pass
        }
    ),
    "detect/detections": _schema(
        {
            "det_id": _id(),
            "pass_id": _id(),
            "time_utc": _utc(),
            "x_m": _num(),
            "y_m": _num(),
            "peak_ratio_vv_db": _num(),
            "peak_ratio_vh_db": _num(),
            "pol_agree": _flag(),
            "n_px": _num(int, ge=1),
            "size_class": _in("small", "medium", "large"),
            "ghost": _flag(),
            "p_boat": _prob(),
        }
    ),
    "match/events": _schema(
        {
            "event_id": _id(),
            "event_type": _event_type,
            "time_utc": _utc(),
            "x_m": _num(),
            "y_m": _num(),
            "cell_id": pa.Column(str, nullable=False),
            "p": _prob(),
            "duration_min": _num(nullable=True, ge=0),
            "ship_key": pa.Column(str, nullable=True),  # salted hash, internal to match/ and fuse/
            "matched": _flag(),
        }
    ),
    "aggregate/observed": _schema(
        {
            "cell_id": pa.Column(str, nullable=False),
            "level": _in(2000, 10000),
            "date": _date(),
            "event_type": _event_type,
            "count": _num(ge=0),
            "exposure": _num(ge=0),
        },
        _count_needs_exposure,
    ),
    "forecast/expected": _schema(
        {
            "cell_id": pa.Column(str, nullable=False),
            "date": _date(),
            "event_type": _event_type,
            "mu": _num(ge=0),
            "phi": _num(ge=0),
            "lo90": _num(ge=0),
            "hi90": _num(ge=0),
            "model": pa.Column(str, nullable=False),
            "fold": _num(
                "Int64", nullable=True
            ),  # 0 for the live forecast (evaluation window), fold number 1..k in backtests
        },
        pa.Check(lambda df: df["lo90"] <= df["hi90"], error="lo90 > hi90"),
    ),
    "fuse/cells": _schema(
        {
            "cell_id": pa.Column(str, nullable=False),
            "date": _date(),
            "event_type": _event_type,
            "p_mid": _prob(),
            "bh_flag": _flag(),
            "gi_z": _num(),
            "cusum_s": _num(ge=0),
            "context": _prob(),
            "U": _prob(),
            "y": _num(ge=0),  # (C + 0.5) / (mu + 0.5) for this row (#87)
            "y_week": _num(
                ge=0
            ),  # (sum C + 0.5) / (sum mu + 0.5) over the cell's ISO week, on each day row (#87)
            "agreement": _num(int, ge=0, le=4),
        }
    ),
    "fuse/sites": _schema(
        {
            "site_id": _id(),
            "x_m": _num(),
            "y_m": _num(),
            "n_slowdowns": _num(int, ge=0),
            "S": _num(ge=0),
            "p_perm": _prob(),
            "bh_flag": _flag(),
            "recurrence": _num(int, ge=0),
            "followup_unobserved": _num(int, ge=0),
            "agreement": _num(int, ge=0, le=4),
            "reasons": _str_list(),
            "top_piers": _str_list(),
            "p_comb": _later(_prob()),  # L3: Cauchy-combined p over merged agents
            "comb_flag": _later(_flag()),  # L3: BH on calibrated p_comb
            "agreement_merged": _later(_num(int, ge=0)),  # L3: merged agents that flag the site
            "p_site": _later(_prob()),  # L4: site value from the model rung in use
            "model_rung": _later(
                _num(int, ge=0, le=3)
            ),  # L4: 0 statistics only ... 3 mixture of experts
            # #320 briefing-card evidence (P6; definitions in docs/specs/P6.md), optional like the learning columns
            "check_rare_slowdown": _later(
                _flag()
            ),  # strongest link's slowdown cell-day in the top top_frac
            "check_followup_seen": _later(_flag()),  # at least one slowdown with L > 0
            "check_outside_fishing": _later(
                _flag_or_na()
            ),  # inshore_frac < inshore_max; NA: no inshore map
            "top_piers_hours": _later(
                _float_list(ge=0)
            ),  # sea hours to each of top_piers, same order
        },
        _same_length("top_piers", "top_piers_hours"),
    ),
    "fuse/fisheries": _schema(  # #346 / #321: one row per fisheries candidate cell and ISO week (P6 writes, P7 reads)
        {
            "cell_id": pa.Column(str, nullable=False),  # 2 km
            "week": _date(),  # the Monday
            "count": _num(ge=0),  # the week's dark_medium soft count
            "mu": _num(ge=0),  # ... and its expected count
            "y_fish": _num(ge=0),  # (count + 0.5) / (mu + 0.5)
            "y_fish_lo": _num(ge=0),  # the range from the 90% interval
            "y_fish_hi": _num(ge=0),
            "p_mid": _prob(),  # mid-p tail of the weekly count
            "flag": _flag(),  # BH at fdr_q across all cell-weeks
            "in_closed_area": _flag_or_na(),  # NA where no closed-areas layer covers the cell (#322)
            "reasons": _str_list(),
            "top_harbours": _str_list(),  # pier ids
            "top_harbours_hours": _float_list(ge=0),  # same length and order as top_harbours
            "lens": _in("fisheries"),
        },
        _same_length("top_harbours", "top_harbours_hours"),
        pa.Check(lambda df: df["y_fish_lo"] <= df["y_fish_hi"], error="y_fish_lo > y_fish_hi"),
    ),
    "fuse/piers": _schema(  # #88: one row per pier
        {
            "pier_id": _id(),
            "P_j": _num(ge=0),  # sum over scored sites of S x exp(-T / 1 h), T = sea travel hours
        }
    ),
    "fuse/links": _schema(  # #98: one row per slowdown with a link score
        {
            "site_id": _id(),
            "L": _prob(),
            "age_days": _num(ge=0),  # per site, sum of L x 0.5^(age_days / 30) = S in fuse/sites
        }
    ),
}


def check(name: str, frame: pd.DataFrame) -> pd.DataFrame:
    """Validate a stage frame; raises pandera.errors.SchemaErrors listing every broken rule. Returns the (coerced) frame."""
    return SCHEMAS[name].validate(frame, lazy=True)


# Non-tabular stage files. Rasters are checked as arrays (reading and writing GeoTIFFs needs rasterio, which is P3's
# and P2's business); JSON files are checked as plain dicts.
_RASTERS = {
    "reference/sea_250m": 250,
    "reference/land_mask_10m": 10,
    "reference/static_mask_10m": 10,
}


def check_raster(
    name: str, array: np.ndarray, *, pixel_m: float, origin: tuple[float, float] | None = None
) -> np.ndarray:
    """uint8 0/1, 2-D, at the right pixel size; the 10 m masks must start at the config origin (x0, y0), gap 5."""
    if name not in _RASTERS:
        raise KeyError(f"unknown raster {name!r}")
    if array.ndim != 2 or array.dtype != np.uint8:
        raise ValueError(f"{name}: expected a 2-D uint8 array, got {array.ndim}-D {array.dtype}")
    if not np.isin(array, (0, 1)).all():
        raise ValueError(f"{name}: values must be 0 or 1")
    if pixel_m != _RASTERS[name]:
        raise ValueError(f"{name}: pixel size must be {_RASTERS[name]} m, got {pixel_m}")
    if name.endswith("_10m") and origin is not None:
        from core.grid import _origin

        if tuple(origin) != _origin():
            raise ValueError(f"{name}: origin {origin} is not the config origin {_origin()}")
    return array


_ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$")


def _plan(obj: Mapping[str, Any]) -> None:
    if not obj or not set(obj) <= {"ship", "aircraft"}:
        raise ValueError("plan: keys must be 'ship' and/or 'aircraft'")
    for asset, stops in obj.items():
        for i, s in enumerate(stops):
            if (
                not isinstance(s.get("id"), str)
                or not _ISO_UTC.match(str(s.get("arrival_utc")))
                or not s.get("dwell_h", -1) >= 0
            ):
                raise ValueError(
                    f"plan: {asset} stop {i} needs id (str), arrival_utc (ISO UTC string) and dwell_h >= 0"
                )
            # L5 (docs/learning.md): optional bandit fields
            if "theta" in s and not 0 <= s["theta"] <= 1:
                raise ValueError(f"plan: {asset} stop {i} theta must be in [0, 1]")
            if "reason" in s and s["reason"] not in ("exploit", "explore"):
                raise ValueError(f"plan: {asset} stop {i} reason must be exploit or explore")
            if "day" in s and s["day"] not in range(7):  # rev 2: day of the planning week
                raise ValueError(f"plan: {asset} stop {i} day must be 0-6")


_SNAPSHOT_KEYS = {"meta", "basemap", "cells", "sites", "piers", "plan", "validation"}


def _snapshot(obj: Mapping[str, Any]) -> None:
    if set(obj) != _SNAPSHOT_KEYS:
        raise ValueError(
            f"snapshot: keys must be exactly {sorted(_SNAPSHOT_KEYS)}, got {sorted(obj)}"
        )
    if obj["meta"].get("data_label") not in ("simulated", "real", "mixed"):
        raise ValueError("snapshot: meta.data_label must be simulated, real or mixed")
    _plan(obj["plan"])


def _bandit_state(obj: Mapping[str, Any]) -> None:
    """L5: {site_id: {alpha, beta, last_visit_week}}; alpha, beta > 0."""
    for site, st in obj.items():
        week = st.get("last_visit_week")
        if not (st.get("alpha", 0) > 0 and st.get("beta", 0) > 0) or not (
            week is None or isinstance(week, int)
        ):
            raise ValueError(
                f"bandit_state: {site!r} needs alpha > 0, beta > 0, last_visit_week int or null"
            )


JSON_CHECKS = {
    "patrol/plan": _plan,
    "export/snapshot": _snapshot,
    "patrol/bandit_state": _bandit_state,
}


def check_json(name: str, obj: Mapping[str, Any]) -> Mapping[str, Any]:
    JSON_CHECKS[name](obj)
    return obj
