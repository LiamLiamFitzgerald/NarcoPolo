"""Static raw layers: osm_piers.geojson, coastline.gpkg, inshore/*.gpkg, infomar_bathy.tif. TODO(P1): issue 'sim: static raw layers'. Reads the SimWorld only."""

from sim.world import SimWorld


def write_static(world: SimWorld) -> None:
    del world  # no-op until the static-layers issue lands
