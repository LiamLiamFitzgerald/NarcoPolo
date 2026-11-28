from datetime import date

import pandas as pd
import pytest

from core.time import iso_week, utc, utc_date

NAIVE = ["2026-11-27 12:00", pd.Timestamp("2026-11-27"), pd.Timestamp("2026-11-27").to_pydatetime()]


@pytest.mark.parametrize("naive", NAIVE)
def test_naive_raises(naive):
    with pytest.raises(ValueError):
        utc(naive)


def test_converts_to_utc():
    assert utc("2026-11-27T23:30:00-02:00") == pd.Timestamp("2026-11-28T01:30:00Z")
    assert str(utc("2026-11-27T12:00:00+00:00").tzinfo) == "UTC"


def test_utc_date_uses_the_utc_day():
    assert utc_date("2026-11-27T23:30:00-02:00") == date(2026, 11, 28)


def test_iso_week_year_boundary():
    assert iso_week(date(2026, 11, 27)) == (2026, 48)
    assert iso_week(date(2027, 1, 1)) == (2026, 53)  # ISO year differs from calendar year
