"""Stage files: validated on every read and write, and stamped with the config keys they were built from (A10)."""

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.config import Config, load
from core.schemas import SCHEMAS, check

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
_GPKG = {
    "reference/cells",
    "reference/piers",
}  # layers of reference/layers.gpkg, written by P3 with geopandas
_STAMP = b"narco"


def stage_path(name: str) -> Path:
    if name not in SCHEMAS:
        raise KeyError(f"unknown stage file {name!r}")
    root = Path(os.environ.get("NARCO_DATA", ROOT / "data"))
    return root / ("reference/layers.gpkg" if name in _GPKG else f"{name}.parquet")


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


def _no_gpkg(name: str) -> None:
    if name in _GPKG:
        raise NotImplementedError(
            f"{name} lives in a GeoPackage: P3 writes it with geopandas and validates with core.schemas.check"
        )


def write_stage(name: str, frame: pd.DataFrame, provenance: Literal["simulated", "real"]) -> Path:
    _no_gpkg(name)
    frame = check(name, frame)  # refuse to write a broken file
    cfg, _ = load(CONFIG_PATH)
    stamp = {
        "provenance": provenance,
        "seed": cfg["seed"] if provenance == "simulated" else "real",
        "config_hash": _keys_hash(cfg, _keys(cfg, name, provenance)),
    }
    table = pa.Table.from_pandas(frame, preserve_index=False)
    table = table.replace_schema_metadata(
        {**(table.schema.metadata or {}), _STAMP: json.dumps(stamp).encode()}
    )
    path = stage_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path


def read_stage(name: str) -> pd.DataFrame:
    _no_gpkg(name)
    table = pq.read_table(stage_path(name))
    raw = (table.schema.metadata or {}).get(_STAMP)
    if raw is None:
        raise ValueError(f"{name} carries no config stamp: it was not written by core.io")
    stamp = json.loads(raw)
    cfg, _ = load(CONFIG_PATH)
    if _keys_hash(cfg, _keys(cfg, name, stamp["provenance"])) != stamp["config_hash"]:
        raise ValueError(
            f"{name} is stale: the config keys it reads changed since it was written; rerun its stage"
        )
    return check(name, table.to_pandas())
