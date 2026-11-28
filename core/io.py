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
import pyogrio

from core.config import Config, latest_dates, load, snapshot_date
from core.schemas import JSON_CHECKS, SCHEMAS, check, check_json

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
_GPKG = {
    "reference/cells": "cells",
    "reference/piers": "piers",
    "reference/land": "land",
    "reference/closed_areas": "closed_areas",  # #322
}  # layers of reference/layers.gpkg
_STAMP = b"narco"


def stage_path(name: str) -> Path:
    if name not in SCHEMAS:
        raise KeyError(f"unknown stage file {name!r}")
    root = Path(os.environ.get("NARCO_DATA", ROOT / "data"))
    return root / ("reference/layers.gpkg" if name in _GPKG else f"{name}.parquet")


RASTERS = ("reference/sea_250m", "reference/land_mask_10m", "reference/static_mask_10m")


def raster_path(name: str) -> Path:
    """Where P3 writes and P4/P7 read the reference rasters (#85); check them with core.schemas.check_raster."""
    if name not in RASTERS:
        raise KeyError(f"unknown raster {name!r}")
    return stage_path("aggregate/observed").parent.parent / f"{name}.tif"


def raw_root() -> Path:
    """raw/ (or $NARCO_RAW): the shape of what P2 downloads, which the simulator imitates."""
    return Path(os.environ.get("NARCO_RAW", ROOT / "raw"))


def truth_path() -> Path:
    """sim/truth.parquet under the data root; only validate reads it."""
    return stage_path("aggregate/observed").parent.parent / "sim" / "truth.parquet"


_KNOWN: dict[tuple[str, int], frozenset[str]] = {}


def _known_cells() -> frozenset[str]:
    """cell_ids in reference/layers.gpkg, cached until the file changes."""
    path = stage_path("reference/cells")
    if not path.exists():
        raise FileNotFoundError(
            "reference/cells must be written before any file that has a cell_id"
        )
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _KNOWN:
        ids = pyogrio.read_dataframe(
            path, layer=_GPKG["reference/cells"], columns=["cell_id"], read_geometry=False
        )
        _KNOWN.clear()
        _KNOWN[key] = frozenset(ids["cell_id"])
    return _KNOWN[key]


def _check_cells_exist(name: str, frame: pd.DataFrame) -> None:
    """Invariant: every cell_id exists in reference/layers.gpkg (the cells layer itself is the reference)."""
    if name == "reference/cells" or "cell_id" not in frame.columns:
        return
    unknown = set(frame["cell_id"]) - _known_cells()
    if unknown:
        raise ValueError(
            f"{name}: {len(unknown)} cell_id(s) not in reference/cells, e.g. {sorted(unknown)[:3]}"
        )


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
    return [
        *cfg["reads"].get(name, ["x0", "y0", "region_bbox"]),
        *(["sim"] if provenance == "simulated" else []),
    ]


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


def _typed_empty(name: str, table: pa.Table) -> pa.Table:
    """A 0-row frame gives Arrow type `null` to untyped columns; give them the type a non-empty file has (#171):
    list<string> for the list-of-str columns, list<double> for the list-of-number ones, string for the rest."""
    kinds = {
        "not a list of str": pa.list_(pa.string()),
        "not a list of numbers": pa.list_(pa.float64()),
    }
    lists = {
        c: kinds[ch.error]
        for c, col in SCHEMAS[name].columns.items()
        for ch in col.checks
        if getattr(ch, "error", None) in kinds
    }
    fields = [
        f.with_type(lists.get(f.name, pa.string())) if pa.types.is_null(f.type) else f
        for f in table.schema
    ]
    return table.cast(pa.schema(fields, metadata=table.schema.metadata))


def write_stage(name: str, frame: pd.DataFrame, provenance: Literal["simulated", "real"]) -> Path:
    frame = check(name, frame)  # refuse to write a broken file
    _check_cells_exist(name, frame)
    cfg, _ = load(CONFIG_PATH)
    stamp = _stamp(cfg, name, provenance)
    path = stage_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if name in _GPKG:
        gpd.GeoDataFrame(frame, crs=32629).to_file(path, layer=_GPKG[name], driver="GPKG")
        _sidecar(name).write_text(json.dumps(stamp))
        return path
    if "date" in frame.columns:  # one stored type, timestamp[ns], whatever the writer passed (#171)
        frame = frame.assign(date=pd.to_datetime(frame["date"]).astype("datetime64[ns]"))
    table = _typed_empty(name, pa.Table.from_pandas(frame, preserve_index=False))
    table = table.replace_schema_metadata(
        {**(table.schema.metadata or {}), _STAMP: json.dumps(stamp).encode()}
    )
    pq.write_table(table, path)
    return path


def read_provenance(name: str) -> Literal["simulated", "real"]:
    """The provenance in a stage file's core.io stamp."""
    if name in _GPKG:
        sidecar = _sidecar(name)
        raw = sidecar.read_bytes() if sidecar.exists() else None
    else:
        raw = (pq.read_schema(stage_path(name)).metadata or {}).get(_STAMP)
    if raw is None:
        raise ValueError(f"{name} carries no config stamp: it was not written by core.io")
    return json.loads(raw)["provenance"]


def read_cells() -> pd.DataFrame:
    """reference/cells without geometry."""
    return pd.DataFrame(read_stage("reference/cells").drop(columns="geometry"))


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
    frame = check(name, read())
    _check_cells_exist(name, frame)
    if (
        "date" in frame.columns
    ):  # one type for every reader: midnight timestamps, whatever the writer used
        frame["date"] = pd.to_datetime(frame["date"])
    return frame


def json_path(name: str) -> Path:
    if name not in JSON_CHECKS:
        raise KeyError(f"unknown JSON stage file {name!r}")
    return stage_path("aggregate/observed").parent.parent / f"{name}.json"


def write_json_stage(
    name: str, obj: dict[str, Any], provenance: Literal["simulated", "real"]
) -> Path:
    """patrol/plan and export/snapshot: checked, then written with a sidecar stamp so the file itself keeps its shape."""
    check_json(name, obj)
    cfg, _ = load(CONFIG_PATH)
    path = json_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, allow_nan=False))
    path.with_suffix(".stamp.json").write_text(json.dumps(_stamp(cfg, name, provenance)))
    return path


def read_json_stage(name: str) -> dict[str, Any]:
    path = json_path(name)
    sidecar = path.with_suffix(".stamp.json")
    if not sidecar.exists():
        raise ValueError(f"{name} carries no config stamp: it was not written by core.io")
    _stale(load(CONFIG_PATH)[0], name, json.loads(sidecar.read_text()))
    obj = json.loads(path.read_text())
    check_json(name, obj)
    return obj
