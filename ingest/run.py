"""make fetch: every raw/ file for the region and windows in config; idempotent through the cache."""

from datetime import UTC, datetime, timedelta

from core.config import Config
from ingest import _stub, era5, gfw, osm, s1, static


def fetch_all(config: Config) -> None:
    bbox = _stub.region(config)
    # last full UTC day; T is fixed later from the data
    end = datetime.now(UTC).date() - timedelta(days=1)
    ship_start = end - timedelta(days=config["ship_history_days"] - 1)
    radar_start = end - timedelta(days=config["radar_history_days"] - 1)

    weather = era5.fetch_era5(bbox, radar_start, end)  # ERA5 first, to pick the calm passes
    passes = s1.select_passes(s1.list_passes(bbox, radar_start, end), weather)
    for row in passes[passes["downloaded"]].to_dict("records"):
        s1.fetch_scene(row)
    gfw.fetch_sar(bbox, ship_start, end)
    gfw.fetch_presence(bbox, ship_start, end)
    osm.fetch_piers(bbox)
    osm.fetch_coastline(bbox)
    static.fetch_inshore()
    static.fetch_bathy()
