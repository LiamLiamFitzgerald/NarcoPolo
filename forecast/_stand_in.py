"""Placeholders for core.split and core.grid until P1 lands core/.

shortcut: mirrors docs/specs/P1.md; delete this file and import from core once core/split
and core/grid exist on integration.
"""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Split:
    cutoff: pd.Timestamp
    embargo_days: int = 7
    test_days: int = 7

    def train(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame[frame["date"] < self.cutoff]

    def test(self, frame: pd.DataFrame) -> pd.DataFrame:
        start = self.cutoff + pd.Timedelta(days=self.embargo_days)
        end = start + pd.Timedelta(days=self.test_days)
        return frame[(frame["date"] >= start) & (frame["date"] < end)]

    def assert_train(self, frame: pd.DataFrame) -> None:
        if (frame["date"] >= self.cutoff).any():
            raise ValueError(
                f"look-ahead: training rows on or after cutoff {self.cutoff.date()}"
            )


def folds(
    T: pd.Timestamp, k_max: int, embargo_days: int, test_days: int
) -> list[Split]:
    """Fold k tests [T - 7k + 1, T - 7k + 7]; its cutoff sits one embargo before the test start."""
    return [
        Split(T - pd.Timedelta(days=7 * k - 1 + embargo_days), embargo_days, test_days)
        for k in range(1, k_max + 1)
    ]


def parent(cell_id: str) -> str:
    _, ix, iy = cell_id.split("_")
    return f"10000_{int(ix) // 5}_{int(iy) // 5}"
