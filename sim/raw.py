"""raw/ files other than s1: GFW, ERA5, static layers, manifest. TODO(P1): issue 'sim: raw/ files'. Reads the SimWorld only."""

from sim.world import SimWorld


def write_raw(world: SimWorld) -> None:
    del world  # no-op until the raw issue lands
