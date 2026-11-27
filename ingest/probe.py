"""Friday go/no-go: one Sentinel-1 crop and one GFW presence query."""


def probe() -> tuple[bool, bool, str]:
    # shortcut: the offline stub never claims a success it did not see; replace with one real crop + one GFW query
    return False, False, "stub: no network call made; continue on the simulator"
