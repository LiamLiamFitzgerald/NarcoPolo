"""Static map of normal at sea: cells and layers, masks, piers and travel times (docs/specs/P3.md)."""

from core import io

_STAGES = ("reference/cells", "reference/piers", "reference/travel_hours")


def run() -> None:
    """make all. On the simulator (no raw/), `make sim` already wrote the reference files: check them and stop."""
    if not (io.stage_path("reference/travel_hours").parent.parent / "raw").exists():
        for name in _STAGES:
            io.read_stage(name)
        return
    raise NotImplementedError("reference on real data: #34, #35, #36")
