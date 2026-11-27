"""Placeholders for core.observed and core.grid until P1 lands core/.

shortcut: mirrors docs/specs/P1.md; delete this file and import from core once core/observed
and core/grid exist on integration.
"""

import pandas as pd

OBSERVED_COLUMNS = ["cell_id", "level", "date", "event_type", "count", "exposure"]


class Observed:
    """A frame of soft counts that always travel with their exposure (principle 4)."""

    def __init__(self, frame: pd.DataFrame) -> None:
        missing = set(OBSERVED_COLUMNS) - set(frame.columns)
        if missing:
            raise ValueError(f"Observed is missing columns {sorted(missing)}")
        if (frame["exposure"] < 0).any() or (frame["count"] < 0).any():
            raise ValueError("count and exposure must be >= 0")
        if ((frame["count"] > 0) & (frame["exposure"] == 0)).any():
            raise ValueError("a count > 0 needs exposure > 0")
        self.frame = frame[OBSERVED_COLUMNS].reset_index(drop=True)

    def observed_rows(self) -> pd.DataFrame:
        return self.frame[self.frame["exposure"] > 0]

    def rate(self) -> pd.Series:
        rows = self.observed_rows()
        return rows["count"] / rows["exposure"]


def parent(cell_id: str) -> str:
    """10 km parent of a 2 km cell: (ix // 5, iy // 5)."""
    _, ix, iy = cell_id.split("_")
    return f"10000_{int(ix) // 5}_{int(iy) // 5}"
