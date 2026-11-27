"""Stage files: validated on every read and write, and stamped with the config keys they were built from (A10)."""

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.config import Config, latest_dates, load, snapshot_date
from core.schemas import SCHEMAS, check

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
_GPKG = {"reference/cells": "cells", "reference/piers": "piers"}  # layers of reference/layers.gpkg
_STAMP = b"narco"


def stage_path(name: str) -> Path:
    if name not in SCHEMAS:
        raise KeyError(f"unknown stage file {name!r}")
    root = Path(os.environ.get("NARCO_DATA", ROOT / "data"))
    return root / ("reference/layers.gpkg" if name in _GPKG else f"{name}.parquet")


def truth_path() -> Path:
    """sim/truth.parquet under the data root; only validate reads it."""
    return stage_path("aggregate/observed").parent.parent / "sim" / "truth.parquet"


def write_snapshot(manifest: Mapping[str, Any]) -> Path:
    """data/snapshot.json: T and each feed's latest date, so modules that may not read raw/ (P5) still know them (A11).
    Written by ingest.fetch_all after it updates the manifest, and by the simulator."""
    dates = latest_dates(manifest)
    path = stage_path("aggregate/observed").parent.parent / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "T": snapshot_date(manifest).isoformat(),
                **{k: v.isoformat() for k, v in dates.items()},
            },
            indent=1,
        )
    )
    return path


def read_snapshot() -> dict[str, date]:
    """Keys: T, radar, gfw_presence, gfw_sar, era5."""
    raw = json.loads((stage_path("aggregate/observed").parent.parent / "snapshot.json").read_text())
    return {k: date.fromisoformat(v) for k, v in raw.items()}


def _plain(x: Any) -> Any:
    if isinstance(x, Mapping):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, tuple | list):
        return [_plain(v) for v in x]
    return x


def _keys_hash(cfg: Config, keys: list[str]) -> str:
    blob = json.dumps({k: _plain(cfg[k]) for k in sorted(keys)}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _keys(cfg: Config, name: str, provenance: str) -> list[str]:
    return [*cfg["reads"][name], *(["sim"] if provenance == "simulated" else [])]


def _stamp(cfg: Config, name: str, provenance: str) -> dict[str, Any]:
    return {
        "provenance": provenance,
        "seed": cfg["seed"] if provenance == "simulated" else "real",
        "config_hash": _keys_hash(cfg, _keys(cfg, name, provenance)),
    }


def _sidecar(
    name: str,
) -> Path:  # a GeoPackage has no file-level metadata we control, so its layers get a stamp file
    return stage_path(name).with_name(f"layers.{_GPKG[name]}.stamp.json")


def _stale(cfg: Config, name: str, stamp: dict[str, Any]) -> None:
    if _keys_hash(cfg, _keys(cfg, name, stamp["provenance"])) != stamp["config_hash"]:
        raise ValueError(
            f"{name} is stale: the config keys it reads changed since it was written; rerun its stage"
        )


def write_stage(name: str, frame: pd.DataFrame, provenance: Literal["simulated", "real"]) -> Path:
    frame = check(name, frame)  # refuse to write a broken file
    cfg, _ = load(CONFIG_PATH)
    stamp = _stamp(cfg, name, provenance)
    path = stage_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if name in _GPKG:
        gpd.GeoDataFrame(frame, crs=32629).to_file(path, layer=_GPKG[name], driver="GPKG")
        _sidecar(name).write_text(json.dumps(stamp))
        return path
    table = pa.Table.from_pandas(frame, preserve_index=False)
    table = table.replace_schema_metadata(
        {**(table.schema.metadata or {}), _STAMP: json.dumps(stamp).encode()}
    )
    pq.write_table(table, path)
    return path


def read_stage(name: str) -> pd.DataFrame:
    if name in _GPKG:
        sidecar = _sidecar(name)
        raw = sidecar.read_bytes() if sidecar.exists() else None
        read = lambda: gpd.read_file(stage_path(name), layer=_GPKG[name])
    else:
        table = pq.read_table(stage_path(name))
        raw = (table.schema.metadata or {}).get(_STAMP)
        read = table.to_pandas
    if raw is None:
        raise ValueError(f"{name} carries no config stamp: it was not written by core.io")
    stamp = json.loads(raw)
    _stale(load(CONFIG_PATH)[0], name, stamp)
    return check(name, read())
