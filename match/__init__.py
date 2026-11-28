"""P4 match: GFW/AIS matching, dark_small and slowdown events."""

from core import io
from match.events import (
    dark_small_events,
    match,
    ship_key,
    slowdowns_from_presence,
    slowdowns_from_tracks,
    write_events,
)

__all__ = [
    "dark_small_events",
    "match",
    "run",
    "ship_key",
    "slowdowns_from_presence",
    "slowdowns_from_tracks",
    "write_events",
]


def run() -> None:
    """make all entry point (DECISIONS.md 2026-11-27 18:30).

    Simulator: `make sim` already wrote the events file; it is re-validated and kept (detect keeps the
    simulator's detections, so there is nothing new to match).
    Real data: slowdowns_from_presence needs GFW presence on the 2 km grid, which reference.regrid_presence (P3)
    computes but no stage file holds yet, and match may import only core (TODO(P1/P3) contract, #183).
    """
    if io.read_provenance("detect/detections") == "simulated":
        io.write_stage("match/events", io.read_stage("match/events"), "simulated")
        return
    raise NotImplementedError(
        "match on real data: GFW presence on the 2 km grid has no stage file yet (P3/P1 contract, #183)"
    )
