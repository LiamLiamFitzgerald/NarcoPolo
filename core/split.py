"""Time split with an embargo. Every fit takes a Split and refuses data at or after the cutoff."""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True)
class Split:
    cutoff: date
    embargo_days: int = 7
    test_days: int = 7

    def _d(self, frame: pd.DataFrame) -> pd.Series:
        return pd.to_datetime(frame["date"])

    def train(self, frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(frame[self._d(frame) < pd.Timestamp(self.cutoff)])

    def test(self, frame: pd.DataFrame) -> pd.DataFrame:
        lo = pd.Timestamp(self.cutoff + timedelta(days=self.embargo_days))
        hi = lo + pd.Timedelta(days=self.test_days)
        d = self._d(frame)
        return pd.DataFrame(frame[(d >= lo) & (d < hi)])

    def assert_train(self, frame: pd.DataFrame) -> None:
        late = self._d(frame) >= pd.Timestamp(self.cutoff)
        if late.any():
            raise ValueError(
                f"{int(late.sum())} training rows are at or after the cutoff {self.cutoff}: look-ahead"
            )


def folds(T: date, k_max: int) -> list[Split]:
    """Fold k tests days [T-7k+1, T-7k+7]; its cutoff is the 7-day embargo before that."""
    return [Split(T - timedelta(days=7 * k + 6)) for k in range(1, k_max + 1)]
