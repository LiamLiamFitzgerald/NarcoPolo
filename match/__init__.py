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

__all__ = ["dark_small_events", "match", "run", "ship_key", "slowdowns_from_presence", "slowdowns_from_tracks", "write_events"]


def run() -> None:
    """make all entry point (DECISIONS.md 2026-11-27 18:30).

    Stub: passes the simulated match/events through core.io, which re-validates it.
    TODO(P4): build events from detect/detections and the GFW feeds once those land in core.io.
    """
    io.write_stage("match/events", io.read_stage("match/events"), "simulated")
