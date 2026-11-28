import numpy as np
import pandas as pd
import pandera.pandas as pa
import pytest
from pandera.errors import SchemaErrors
from shapely.geometry import Point, box

from core.schemas import SCHEMAS, check

T = pd.Timestamp("2026-11-27T12:00:00Z")


def row(**kw):
    return {k: [v] for k, v in kw.items()}


VALID = {
    "reference/cells": row(
        cell_id="2000_0_0",
        level=2000,
        geometry=box(0, 0, 2000, 2000),
        inshore_frac=np.nan,
        lane=False,
        anchorage=False,
        port_zone=False,
        exclusion=False,
        dist_coast_m=500.0,
        static_frac=0.1,
        sea_frac=0.9,
    ),
    "reference/piers": row(pier_id="p1", name="Pier", geometry=Point(1, 1), road_access=True),
    "reference/land": row(id=0, geometry=box(0, 0, 2000, 1000)),
    "reference/travel_hours": row(cell_id="2000_0_0", pier_id="p1", hours=0.5),
    "coverage/exposure": row(
        cell_id="2000_0_0",
        pass_id="s1",
        time_utc=T,
        covered_frac=0.5,
        wind_ms=3.0,
        hs_m=1.0,
        calm=True,
        exposure_small=0.5,
        post_storm=False,
    ),
    "detect/detections": row(
        det_id="d1",
        pass_id="s1",
        time_utc=T,
        x_m=1.0,
        y_m=2.0,
        peak_ratio_vv_db=6.0,
        peak_ratio_vh_db=3.0,
        pol_agree=True,
        n_px=4,
        size_class="small",
        ghost=False,
        p_boat=0.7,
    ),
    "match/events": row(
        event_id="e1",
        event_type="slowdown",
        time_utc=T,
        x_m=1.0,
        y_m=2.0,
        cell_id="2000_0_0",
        p=1.0,
        duration_min=30.0,
        ship_key="abc",
        matched=False,
    ),
    "aggregate/observed": row(
        cell_id="2000_0_0",
        level=2000,
        date=pd.Timestamp("2026-11-27").date(),
        event_type="dark_small",
        count=1.0,
        exposure=2.0,
    ),
    "forecast/expected": row(
        cell_id="2000_0_0",
        date=pd.Timestamp("2026-11-27").date(),
        event_type="dark_small",
        mu=1.0,
        phi=1.0,
        lo90=0.0,
        hi90=3.0,
        model="ewma",
        fold=None,
    ),
    "fuse/cells": row(
        cell_id="2000_0_0",
        date=pd.Timestamp("2026-11-27").date(),
        event_type="slowdown",
        p_mid=0.04,
        bh_flag=False,
        gi_z=1.2,
        cusum_s=0.0,
        context=0.5,
        U=0.9,
        y=1.4,
        y_week=1.1,
        agreement=2,
    ),
    "fuse/sites": row(
        site_id="s1",
        x_m=1.0,
        y_m=2.0,
        n_slowdowns=3,
        S=1.5,
        p_perm=0.02,
        bh_flag=True,
        recurrence=2,
        followup_unobserved=0,
        agreement=3,
        reasons=["recurs"],
        top_piers=["p1"],
    ),
    "fuse/piers": row(pier_id="p1", P_j=0.3),
    "fuse/links": row(site_id="s1", L=0.6, age_days=4.0),
}


def frame(name, **over):
    d = {**VALID[name], **{k: [v] for k, v in over.items()}}
    return pd.DataFrame(d)


def test_every_schema_has_a_valid_example():
    assert set(VALID) == set(SCHEMAS)
    for name in SCHEMAS:
        check(name, frame(name))


@pytest.mark.parametrize(
    ("name", "bad"),
    [
        ("aggregate/observed", {"count": 1.0, "exposure": 0.0}),  # the spec's schema test
        ("aggregate/observed", {"exposure": -1.0}),
        ("aggregate/observed", {"event_type": "smuggling"}),
        ("coverage/exposure", {"time_utc": pd.Timestamp("2026-11-27T12:00:00")}),  # naive time
        ("detect/detections", {"p_boat": 1.2}),
        ("detect/detections", {"size_class": "huge"}),
        ("fuse/cells", {"agreement": 5}),
        ("fuse/cells", {"U": -0.1}),
        ("fuse/sites", {"p_perm": 2.0}),
        ("fuse/sites", {"reasons": "recurs"}),  # a string is not a list of str
        ("forecast/expected", {"lo90": 5.0, "hi90": 3.0}),
        ("forecast/expected", {"mu": -1.0}),
        ("reference/cells", {"sea_frac": 0.1}),
        ("reference/cells", {"level": 500}),
        ("match/events", {"p": 1.5}),
    ],
)
def test_broken_rule_is_rejected(name, bad):
    with pytest.raises(pa.errors.SchemaErrors):
        check(name, frame(name, **bad))


def test_extra_column_rejected_so_ship_ids_cannot_leak_past_match():
    for name in ("fuse/cells", "fuse/sites"):
        with pytest.raises(pa.errors.SchemaErrors):
            check(name, frame(name).assign(ship_key="abc"))


def test_unobserved_row_with_zero_count_is_fine_and_ints_are_coerced():
    out = check("aggregate/observed", frame("aggregate/observed", count=0, exposure=0))
    assert out["count"].dtype == float


def test_learning_columns_are_optional_but_checked():
    check("fuse/sites", frame("fuse/sites"))  # without them
    check(
        "fuse/sites",
        frame(
            "fuse/sites", p_comb=0.01, comb_flag=True, agreement_merged=2, p_site=0.4, model_rung=1
        ),
    )
    with pytest.raises(SchemaErrors):
        check("fuse/sites", frame("fuse/sites", p_site=1.5))
