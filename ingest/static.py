"""Inshore fishing layers (BIM / Marine Institute, data.gov.ie) with survey extent, and INFOMAR bathymetry.

Sources (URL + licence) come from config `ingest:` (inshore_layers, survey_extent, infomar_bathy; issues #215,
#216). Nothing is guessed: a source not yet configured gets the empty offline placeholder, recorded as a stub.
Downloads are kept as delivered; the only change is format conversion to GeoPackage / GeoTIFF.
"""

import shutil
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pyogrio
import rasterio.shutil

from core.io import raw_root
from ingest import _stub
from ingest.cache import cached, record

_PX = 10.0  # m, the fixed region grid (issue 5)


def _settings() -> Mapping[str, Any]:
    return _stub.config().get("ingest") or {}


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "narcopolo-ingest"})
    with urllib.request.urlopen(req, timeout=600) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)


def _get(
    source: str, src: Mapping[str, str], rel: str, convert: Callable[[Path, Path], None]
) -> Path:
    """Cache-or-download src["url"], convert it to raw/<rel> and record it with src["licence"]."""
    req = {"source": source, "url": src["url"]}
    if (hit := cached(req)) is not None:
        return hit
    path = raw_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as tmp:
        download = Path(tmp) / Path(src["url"].split("?")[0]).name
        _download(src["url"], download)
        convert(download, path)
    record(req, path, src["licence"])
    return path


def _to_gpkg(download: Path, path: Path) -> None:
    """Every layer of any OGR source (zipped shapefile, GeoJSON, ...) into one GeoPackage; a single layer is
    named after the file, as the simulator names it."""
    layers = [str(name) for name, _ in pyogrio.list_layers(download)]
    for name in layers:
        frame = pyogrio.read_dataframe(download, layer=name)
        out = path.stem if len(layers) == 1 else name
        pyogrio.write_dataframe(frame, path, layer=out, append=path.exists())


def _to_tif(download: Path, path: Path) -> None:
    """One raster as GeoTIFF; a zip must hold exactly one .tif/.tiff."""
    if zipfile.is_zipfile(download):
        with zipfile.ZipFile(download) as z:
            tifs = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
            if len(tifs) != 1:
                raise ValueError(f"expected one GeoTIFF in {download.name}, found {tifs}")
            download = Path(z.extract(tifs[0], download.parent / "unzipped"))
    rasterio.shutil.copy(download, path, driver="GTiff")


def fetch_inshore() -> list[Path]:
    """raw/inshore/<layer>.gpkg per configured fishing layer, plus raw/inshore/survey_extent.gpkg (issue 7)."""
    s = _settings()
    layers: Mapping[str, Mapping[str, str]] = s.get("inshore_layers") or {}
    extent: Mapping[str, str] | None = s.get("survey_extent")
    out = [_get(f"inshore/{n}", src, f"inshore/{n}.gpkg", _to_gpkg) for n, src in layers.items()]
    if extent:
        out.append(_get("inshore/survey_extent", extent, "inshore/survey_extent.gpkg", _to_gpkg))
    stubs = ([] if layers else ["inshore_grounds"]) + ([] if extent else ["survey_extent"])
    for layer in stubs:
        req = _stub.request(f"inshore/{layer}", _stub.region())
        write = lambda p, layer=layer: _stub.empty_gpkg(p, layer, "Polygon")
        out.append(_stub.get(req, f"inshore/{layer}.gpkg", write))
    return out


def fetch_bathy() -> Path:
    """raw/infomar_bathy.tif as delivered (CC BY 4.0; the configured licence carries INFOMAR's attribution line).
    Not configured yet: one NaN pixel at the grid origin, recorded as a stub."""
    if src := _settings().get("infomar_bathy"):
        return _get("infomar_bathy", src, "infomar_bathy.tif", _to_tif)
    cfg = _stub.config()
    depth = np.full((1, 1, 1), np.nan, dtype=np.float32)
    write = lambda p: _stub.geotiff(p, depth, float(cfg["x0"]), float(cfg["y0"]) + _PX, _PX)
    return _stub.get(_stub.request("infomar_bathy", _stub.region()), "infomar_bathy.tif", write)
