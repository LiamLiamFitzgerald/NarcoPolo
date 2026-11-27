"""Azimuth-ambiguity ghost rule.

Spec warning: the offset formula and the metadata field names are unverified. Check on one
real scene with a known bright ship that its ghost appears where predicted before trusting this.
"""

from typing import Any

import numpy as np

from detect._standin import CFG

# TODO(P2): metadata key names are not fixed by the data dictionary; these are the ones P4 reads.
_PRF, _RANGE, _SPEED = "prf_hz", "slant_range_m", "sat_speed_ms"


def ghost_offset_m(meta: dict[str, Any]) -> float | tuple[float, float]:
    """Azimuth displacement lambda R f_PRF / (2 V_s), or the ghost_band_m search band if any is missing."""
    if all(meta.get(k) for k in (_PRF, _RANGE, _SPEED)):
        return CFG["radar_wavelength_m"] * meta[_RANGE] * meta[_PRF] / (2 * meta[_SPEED])
    lo, hi = CFG["ghost_band_m"]
    return (float(lo), float(hi))


def azimuth_heading(meta: dict[str, Any]) -> float:
    """Flight direction in degrees clockwise from grid north: heading_deg, else from orbit direction (issue 6)."""
    if meta.get("heading_deg") is not None:
        return float(meta["heading_deg"])
    key = {"ascending": "heading_ascending_deg", "descending": "heading_descending_deg"}[
        str(meta["orbit_direction"]).lower()
    ]
    if CFG[key] is None:
        raise ValueError(f"no heading_deg in scene meta and config {key} is unset (TODO(P4) question)")
    return float(CFG[key])


def is_ghost(
    cand: Any,
    img: np.ndarray,
    heading: float,
    offset: float | tuple[float, float],
    tol_m: float = CFG["ghost_tol_m"],
    db: float = CFG["ghost_db"],
) -> bool:
    """True if the image has a pixel >= db brighter than the candidate's peak at the azimuth offset.

    cand needs row, col and peak_db. img is the unmasked linear image, so bright land and
    ships the candidate list dropped still count. Searches both sides along heading, tol_m
    across track and either offset +- tol_m or the whole band along track.
    """
    px = CFG["pixel_m"]
    lo, hi = (offset - tol_m, offset + tol_m) if np.isscalar(offset) else offset
    along = np.arange(lo, hi + px, px)
    across = np.arange(-tol_m, tol_m + px, px)
    a, c = np.meshgrid(np.concatenate([along, -along]), across)
    h = np.deg2rad(heading)
    # unit vectors in (east, north); rows grow southwards
    dx, dy = a * np.sin(h) + c * np.cos(h), a * np.cos(h) - c * np.sin(h)
    rows = np.rint(cand["row"] - dy / px).astype(int).ravel()
    cols = np.rint(cand["col"] + dx / px).astype(int).ravel()
    ok = (rows >= 0) & (rows < img.shape[0]) & (cols >= 0) & (cols < img.shape[1])
    if not ok.any():
        return False
    brightest = np.nanmax(img[rows[ok], cols[ok]])
    return bool(10 * np.log10(brightest) >= cand["peak_db"] + db)
