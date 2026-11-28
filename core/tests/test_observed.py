import pandas as pd
import pytest

from core.observed import Observed


def make(rows):
    return pd.DataFrame(
        [("2000_0_0", "fine", "2026-11-01", "dark_small", c, e) for c, e in rows],
        columns=["cell_id", "level", "date", "event_type", "count", "exposure"],
    )


def test_count_with_zero_exposure_rejected():
    with pytest.raises(ValueError, match="exposure = 0"):
        Observed(make([(1, 0)]))


def test_negative_exposure_and_missing_rejected():
    with pytest.raises(ValueError, match="exposure < 0"):
        Observed(make([(0, -1)]))
    with pytest.raises(ValueError, match="missing"):
        Observed(make([(None, 1)]))
    with pytest.raises(ValueError, match="columns"):
        Observed(make([(0, 1)]).drop(columns="level"))


def test_rate_only_where_observed():
    o = Observed(make([(2, 4), (0, 0), (0, 2)]))
    assert list(o.observed_rows().index) == [0, 2]
    assert list(o.rate()) == [0.5, 0.0]  # the unobserved row is not a zero rate, it is absent
    assert len(o.frame) == 3  # but it is kept
