from datetime import date, timedelta

import pandas as pd
import pytest

from core.split import Split, folds

CUT = date(2026, 11, 1)


def days(start: date, n: int) -> pd.DataFrame:
    return pd.DataFrame({"date": [start + timedelta(days=i) for i in range(n)]})


def test_train_and_test_windows():
    f = days(date(2026, 10, 20), 40)
    s = Split(CUT)
    assert max(s.train(f)["date"]) == date(2026, 10, 31)
    t = s.test(f)["date"]
    assert (t.min(), t.max(), len(t)) == (
        date(2026, 11, 8),
        date(2026, 11, 14),
        7,
    )  # 7 embargo days skipped


def test_future_training_row_raises():
    f = days(date(2026, 10, 20), 20)
    s = Split(CUT)
    s.assert_train(s.train(f))
    with pytest.raises(ValueError, match="look-ahead"):
        s.assert_train(f)


def test_folds_match_spec():
    T = date(2026, 11, 27)
    fs = folds(T, 12)
    assert len(fs) == 12
    for k, s in enumerate(fs, start=1):
        f = days(T - timedelta(days=100), 101)
        t = s.test(f)["date"]
        assert (t.min(), t.max()) == (T - timedelta(days=7 * k - 1), T - timedelta(days=7 * k - 7))
    assert fs[0].cutoff == T - timedelta(days=13)
