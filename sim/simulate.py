# pyright: reportCallIssue=false, reportArgumentType=false, reportOperatorIssue=false
# (pandas and numpy scalar typing noise; the tests check the values)
"""A synthetic region with known truth, so every module can be built and tested before real data exists.

Own code only: nothing from detect/, match/, aggregate/, forecast/ or fuse/ is imported (a bug would then appear in
both the simulator and the module it tests). Writes every stage file through core.io, plus truth.parquet that only
validate reads. Not done here (follow-up): raw/-shaped files and radar scene chips.
"""

import hashlib
from datetime import date, timedelta

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import poisson
from shapely.geometry import Point, box

from core import io
from core.config import Config
from core.grid import COARSE, FINE, _origin, cell_id, parent
from sim._scores import cusum, gi_star
from sim.raw import write_raw
from sim.regimes import REGIMES, plant
from sim.scenes import write_scenes
from sim.static import write_static
from sim.world import SimWorld

SITE_COLS = [
    "site_id", "x_m", "y_m", "n_slowdowns", "S", "p_perm", "bh_flag", "recurrence",
    "followup_unobserved", "agreement", "reasons", "top_piers",
]  # fmt: skip
NX, NY = 75, 13  # 150 km along the coast x 26 km out: 975 fine cells; iy = NY - 1 touches the shore
SHORE_FRAC = 0.6  # the shore row is 60% sea
KN = 0.514444


def _rng(cfg: Config, name: str, seed: int) -> np.random.Generator:
    return np.random.default_rng(seed + cfg["sim"]["seed_offsets"][name])


def _p_det(cfg: Config, length_m: np.ndarray | float, wind_ms: np.ndarray | float) -> np.ndarray:
    s = cfg["sim"]
    return 1 / (
        1
        + np.exp(
            -(s["det_a"] + s["det_b"] * np.asarray(length_m) - s["det_c"] * np.asarray(wind_ms))
        )
    )


def _ids(ix: np.ndarray, iy: np.ndarray, s: int = FINE) -> np.ndarray:
    return np.array([cell_id(int(i), int(j), s) for i, j in zip(ix, iy, strict=True)], dtype=object)


def _make_map(cfg: Config) -> dict:
    """Cells in fine-grid order (ix major), piers, and the planted site's cell."""
    x0, y0 = _origin()
    ix, iy = np.meshgrid(np.arange(NX), np.arange(NY), indexing="ij")
    ix, iy = ix.ravel(), iy.ravel()
    dist = (NY - 1 - iy) * FINE + FINE / 2  # centre of the cell to the shore line
    inshore = np.clip(
        (5000 - (dist - FINE / 2)) / FINE, 0, 1
    )  # inshore grounds: within 5 km of the shore
    lane = np.isin(iy, (3, 4))
    anchorage = (ix >= 30) & (ix <= 33) & (iy >= 6) & (iy <= 8)
    port = (ix >= 4) & (ix <= 7) & (iy >= 11)
    wind_farm = (ix >= 55) & (ix <= 57) & (iy >= 5) & (iy <= 7)
    fine = pd.DataFrame(
        {
            "cell_id": _ids(ix, iy),
            "level": FINE,
            "inshore_frac": inshore,
            "lane": lane,
            "anchorage": anchorage,
            "port_zone": port,
            "exclusion": anchorage | port,
            "dist_coast_m": dist,
            "static_frac": wind_farm.astype(float),
            "sea_frac": np.where(iy == NY - 1, SHORE_FRAC, 1.0),
            "ix": ix,
            "iy": iy,
        }
    )
    fine["geometry"] = [
        box(x0 + i * FINE, y0 + j * FINE, x0 + (i + 1) * FINE, y0 + (j + 1) * FINE)
        for i, j in zip(ix, iy, strict=True)
    ]
    fine["pcell"] = [parent(c) for c in fine["cell_id"]]
    g = fine.groupby("pcell", sort=True)
    coarse = pd.DataFrame(
        {
            "inshore_frac": g["inshore_frac"].mean(),
            "lane": g["lane"].any(),
            "anchorage": g["anchorage"].any(),
            "port_zone": g["port_zone"].any(),
            "exclusion": g["exclusion"].any(),
            "dist_coast_m": g["dist_coast_m"].mean(),
            "static_frac": g["static_frac"].mean(),
            "sea_frac": g["sea_frac"].mean().clip(lower=0.2),
        }
    ).reset_index(names="cell_id")
    coarse["level"] = COARSE
    coarse["geometry"] = [
        box(
            x0 + int(p.split("_")[1]) * COARSE,
            y0 + int(p.split("_")[2]) * COARSE,
            x0 + (int(p.split("_")[1]) + 1) * COARSE,
            y0 + (int(p.split("_")[2]) + 1) * COARSE,
        )
        for p in coarse["cell_id"]
    ]
    cols = [
        "cell_id",
        "level",
        "geometry",
        "inshore_frac",
        "lane",
        "anchorage",
        "port_zone",
        "exclusion",
        "dist_coast_m",
        "static_frac",
        "sea_frac",
    ]
    cells = pd.concat([fine[cols], coarse[cols]], ignore_index=True)

    shore_y = y0 + (NY - 1) * FINE + SHORE_FRAC * FINE
    pier_ix = np.array([5, 18, 30, 42, 55, 68])
    piers = pd.DataFrame(
        {
            "pier_id": [f"pier_{i}" for i in range(6)],
            "name": [f"Pier {c}" for c in "ABCDEF"],
            "geometry": [Point(x0 + (i + 0.5) * FINE, shore_y) for i in pier_ix],
            "road_access": [True, True, False, True, False, True],
        }
    )
    return {
        "fine": fine,
        "cells": cells,
        "piers": gpd.GeoDataFrame(piers, geometry="geometry", crs=32629),
    }


def _make_weather(cfg: Config, days: int, seed: int) -> pd.DataFrame:
    rng = _rng(cfg, "weather", seed)
    wind = np.empty(days)
    wind[0] = 5.0
    for t in range(1, days):
        wind[t] = 0.7 * wind[t - 1] + 0.3 * 5.0 + rng.normal(0, 1.5)
    for start in rng.choice(days - 3, size=6, replace=False):  # storms: 1-3 days of extra wind
        wind[start : start + rng.integers(1, 4)] += 8.0
    wind = np.clip(wind, 0.5, None)
    hs = np.clip(0.025 * wind**2 + rng.normal(0, 0.15, days), 0.1, None)
    return pd.DataFrame({"wind_ms": wind, "hs_m": hs, "rough": wind >= cfg["sim"]["rough_wind_ms"]})


def _day_time(start: date, day: float) -> pd.Timestamp:
    return pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=float(day))


def _ship_key(seed: int, i: int) -> str:
    return hashlib.sha256(f"salt-{seed}-{i}".encode()).hexdigest()[:16]


def simulate(config: Config, seed: int, regime: str = "fixed") -> None:
    if regime not in REGIMES:
        raise ValueError(f"unknown regime {regime!r}; expected one of {REGIMES}")
    s = config["sim"]
    days = int(s["days"])
    start = date.fromisoformat(s["start_date"])
    x0, y0 = _origin()
    m = _make_map(config)
    fine, cells, piers = m["fine"], m["cells"], m["piers"]
    n = len(fine)
    weather = _make_weather(config, days, seed)
    rough = weather["rough"].to_numpy()

    # normal small boats: Poisson per cell-day
    rng = _rng(config, "boats", seed)
    t = np.arange(days)[:, None]
    lam = np.exp(
        s["beta0"]
        + s["beta1_inshore"] * fine["inshore_frac"].to_numpy()
        + s["beta2_lane"] * fine["lane"].to_numpy()
        + s["gamma"] * np.sin(2 * np.pi * t / 365)
    )  # days x cells
    counts = rng.poisson(lam)
    day_i, cell_i = np.nonzero(counts)
    rep = counts[day_i, cell_i]
    day_i, cell_i = np.repeat(day_i, rep), np.repeat(cell_i, rep)
    nb = len(day_i)
    boats = pd.DataFrame(
        {
            "kind": "normal_boat",
            "day": day_i + rng.random(nb),
            "cell": cell_i,
            "x_m": x0 + (fine["ix"].to_numpy()[cell_i] + rng.random(nb)) * FINE,
            "y_m": y0 + (fine["iy"].to_numpy()[cell_i] + rng.random(nb)) * FINE,
            "length_m": rng.uniform(*s["small_boat_length_m"], nb),
        }
    )

    # normal ship slowdowns: busy in the anchorage and port zones, nearly absent elsewhere
    rng = _rng(config, "slowdowns", seed)
    hot = (fine["anchorage"] | fine["port_zone"]).to_numpy()
    ship_rate = np.where(hot, s["slowdown_rate_hot"], s["slowdown_rate_cold"])
    # rates are per full sea cell (docs/specs/P3.md), and slowdown exposure is sea_frac, so a 60%-sea shore cell gets
    # 60% of the slowdowns; otherwise its expected count is 0.6 of its true one
    sc = rng.poisson(np.broadcast_to(ship_rate * fine["sea_frac"].to_numpy(), (days, n)))
    sd, sci = np.nonzero(sc)
    sd, sci = np.repeat(sd, sc[sd, sci]), np.repeat(sci, sc[sd, sci])
    ns = len(sd)
    ships = pd.DataFrame(
        {
            "day": sd + rng.random(ns),
            "cell": sci,
            "planted": False,
            "x_m": x0 + (fine["ix"].to_numpy()[sci] + rng.random(ns)) * FINE,
            "y_m": y0 + (fine["iy"].to_numpy()[sci] + rng.random(ns)) * FINE,
            "duration_min": rng.uniform(20, 240, ns),
        }
    )

    # radar passes every 1-3 days over part of the region (east-west footprint in cell units)
    rng = _rng(config, "passes", seed)
    passes, d = [], 0
    while d < days:
        w = rng.uniform(*s["pass_width_frac"]) * NX
        a = rng.uniform(0, NX - w)
        passes.append(
            {
                "pass_id": f"pass_{len(passes):03d}",
                "day": d,
                "time_utc": _day_time(start, d + 0.25 + rng.uniform(0, 0.08)),
                "a": a,
                "b": a + w,
            }
        )
        d += int(rng.integers(1, 4))
    passes = pd.DataFrame(passes)
    # planted drop site 5-20 km offshore, away from the lane, anchorage, port and wind farm
    rng = _rng(config, "pickups", seed)
    ok = (
        fine["dist_coast_m"].between(5000, 20000)
        & ~fine["lane"]
        & ~fine["exclusion"]
        & (fine["static_frac"] == 0)
        & (fine["ix"].between(10, 65))
    ).to_numpy()
    site = int(rng.choice(np.flatnonzero(ok)))
    drop_days, d = [], float(rng.integers(3, 8))
    while d < days:
        drop_days.append(d + rng.uniform(0.3, 0.7))
        # #177: random gaps (a Poisson process, mean drop_interval_days, at least 1 day). A near-fixed 10-day cadence
        # let the site permutation test realign slowdowns with pick-ups by shifting whole periods.
        d += max(1.0, float(rng.exponential(s["drop_interval_days"])))
    # the regime moves or retimes drops with its own stream, so `fixed` consumes no extra draws (docs/learning.md L1)
    pass_days = (
        (passes["time_utc"] - pd.Timestamp(start, tz="UTC")).dt.total_seconds() / 86400
    ).to_numpy()
    drop_days, drop_cells, visit_days, visit_cells = plant(
        config, regime, drop_days, site, ok, fine, pass_days, days,
        np.random.default_rng([seed, REGIMES.index(regime)]),
    )  # fmt: skip
    ccx = x0 + (fine["ix"].to_numpy() + 0.5) * FINE  # cell centres
    ccy = y0 + (fine["iy"].to_numpy() + 0.5) * FINE
    pick_days, pick_cells, picked = [], [], []  # picked: the drop day each pick-up follows
    for dd, dc in zip(drop_days, drop_cells, strict=True):
        if rng.random() >= s["pickup_prob"]:
            continue
        pd_ = dd + rng.uniform(*s["pickup_delay_days"])
        if pd_ < days and rough[int(pd_)] and rng.random() < s["rough_pickup_delay_prob"]:
            while pd_ < days and rough[int(pd_)]:
                pd_ = np.floor(pd_) + 1 + (pd_ % 1)  # next calm day, same time of day
        if pd_ < days:
            pick_days.append(pd_)
            pick_cells.append(dc)
            picked.append(dd)
    pick_days, pick_cells = np.asarray(pick_days, float), np.asarray(pick_cells, int)
    nd, npk = len(drop_days), len(pick_days)
    ships = pd.concat(
        [
            ships,
            pd.DataFrame(
                {
                    "day": drop_days,
                    "cell": drop_cells,
                    "planted": True,
                    "x_m": ccx[drop_cells],
                    "y_m": ccy[drop_cells],
                    "duration_min": rng.uniform(60, 240, nd),
                }
            ),
        ],
        ignore_index=True,
    )
    pickups = pd.DataFrame(
        {
            "kind": "pickup",
            "day": pick_days,
            "cell": pick_cells,
            "x_m": ccx[pick_cells] + rng.normal(0, 300, npk),
            "y_m": ccy[pick_cells] + rng.normal(0, 300, npk),
            "length_m": rng.uniform(*s["small_boat_length_m"], npk),
        }
    )
    boats = pd.concat([boats, pickups], ignore_index=True)

    pass_of_day = {int(r.day): i for i, r in enumerate(passes.itertuples())}

    # coverage/exposure: every pass x every fine cell
    P = len(passes)
    ixs = fine["ix"].to_numpy()
    cov = np.clip(
        np.minimum(passes["b"].to_numpy()[:, None], ixs + 1)
        - np.maximum(passes["a"].to_numpy()[:, None], ixs),
        0,
        1,
    )  # P x cells
    pw = weather.loc[passes["day"].to_numpy()].reset_index(drop=True)
    calm = ~pw["rough"].to_numpy()
    exposure_small = cov * fine["sea_frac"].to_numpy() * calm[:, None]
    # A9: >= storm_hours of hs > storm_hs_m in the storm_lookback_h before the pass; the simulator's weather is daily
    cv = config["coverage"]
    stormy = weather["hs_m"].to_numpy() > cv["storm_hs_m"]
    look = int(cv["storm_lookback_h"] // 24)
    need = int(np.ceil(cv["storm_hours"] / 24))
    post_storm = np.array(
        [stormy[max(0, d - look) : d].sum() >= need for d in passes["day"].astype(int)]
    )
    cell_ids = fine["cell_id"].to_numpy()
    exp_df = pd.DataFrame(
        {
            "cell_id": np.tile(cell_ids, P),
            "pass_id": np.repeat(passes["pass_id"].to_numpy(), n),
            "time_utc": np.repeat(passes["time_utc"].to_numpy(), n),
            "covered_frac": cov.ravel(),
            "wind_ms": np.repeat(pw["wind_ms"].to_numpy(), n),
            "hs_m": np.repeat(pw["hs_m"].to_numpy(), n),
            "calm": np.repeat(calm, n),
            "exposure_small": exposure_small.ravel(),
            "post_storm": np.repeat(post_storm, n),
        }
    )

    # observation: detections with p_det = sigmoid(a + b L - c w), false alarms, ghosts
    rng = _rng(config, "observe", seed)
    bday = boats["day"].astype(int).to_numpy()
    bpass = np.array([pass_of_day.get(int(d), -1) for d in bday])
    bxc = (boats["x_m"].to_numpy() - x0) / FINE
    inside = (
        (bpass >= 0)
        & (bxc >= passes["a"].to_numpy()[bpass])
        & (bxc <= passes["b"].to_numpy()[bpass])
    )
    wind_b = weather["wind_ms"].to_numpy()[bday]
    # principle 5: small boats are looked for on calm passes only, so a rough pass detects nothing (#90)
    calm_b = inside & ~weather["rough"].to_numpy()[bday]
    detected = calm_b & (
        rng.random(len(boats)) < _p_det(config, boats["length_m"].to_numpy(), wind_b)
    )
    boats["detected"], boats["pass"] = detected, np.where(inside, bpass, -1)

    rows = []
    for i in np.flatnonzero(detected):
        L = boats["length_m"][i]
        rows.append(
            (
                boats["pass"][i],
                boats["x_m"][i] + rng.normal(0, 30),
                boats["y_m"][i] + rng.normal(0, 30),
                6 + 0.4 * (L - 6) + rng.normal(0, 1),
                rng.random() < 0.8,
                max(1, round(L / 5)),
                "small" if L < 8 else "medium" if L < 12 else "large",
                False,
                float(np.clip(0.75 + rng.normal(0, 0.1), 0.05, 0.99)),
            )
        )
    depth_km = (NY - 1 + SHORE_FRAC) * FINE / 1000
    for k, pr in enumerate(passes.itertuples()):
        for _ in range(
            rng.poisson(s["false_alarm_per_km2_pass"] * (pr.b - pr.a) * FINE / 1000 * depth_km)
        ):
            rows.append(
                (
                    k,
                    x0 + rng.uniform(pr.a, pr.b) * FINE,
                    y0 + rng.uniform(0, (NY - 1 + SHORE_FRAC) * FINE),
                    3 + rng.normal(0, 0.7),
                    rng.random() < 0.3,
                    1,
                    "small",
                    False,
                    0.15,
                )
            )
    for sh in ships[
        ~ships["planted"]
    ].itertuples():  # a bright ship leaves a ghost at the ambiguity offset
        k = pass_of_day.get(int(sh.day), -1)
        if k >= 0 and passes["a"][k] <= (sh.x_m - x0) / FINE <= passes["b"][k]:
            rows.append(
                (
                    k,
                    sh.x_m + s["ghost_offset_m"],
                    sh.y_m,
                    4 + rng.normal(0, 0.5),
                    True,
                    2,
                    "large",
                    True,
                    0.03,
                )
            )
    det = pd.DataFrame(
        rows,
        columns=["k", "x_m", "y_m", "vv", "pol_agree", "n_px", "size_class", "ghost", "p_boat"],
    )
    det = det[~pw["rough"].to_numpy()[det["k"].to_numpy(int)]].reset_index(
        drop=True
    )  # false alarms and ghosts too
    detections = pd.DataFrame(
        {
            "det_id": [f"det_{i:05d}" for i in range(len(det))],
            "pass_id": passes["pass_id"].to_numpy()[det["k"].astype(int)],
            "time_utc": passes["time_utc"].to_numpy()[det["k"].astype(int)],
            "x_m": det["x_m"],
            "y_m": det["y_m"],
            "peak_ratio_vv_db": det["vv"],
            "peak_ratio_vh_db": det["vv"] - 3 + rng.normal(0, 1, len(det)),
            "pol_agree": det["pol_agree"],
            "n_px": det["n_px"],
            "size_class": det["size_class"],
            "ghost": det["ghost"],
            "p_boat": det["p_boat"],
        }
    )

    # events: dark small boats from non-ghost detections, slowdowns from ships
    def cid(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        i = np.clip(np.floor((np.asarray(x) - x0) / FINE), 0, NX - 1).astype(int)
        j = np.clip(np.floor((np.asarray(y) - y0) / FINE), 0, NY - 1).astype(int)
        return _ids(i, j)

    dk = detections[~detections["ghost"]]
    dark = pd.DataFrame(
        {
            "event_id": [f"ev_d_{i:05d}" for i in range(len(dk))],
            "event_type": "dark_small",
            "time_utc": dk["time_utc"],
            "x_m": dk["x_m"],
            "y_m": dk["y_m"],
            "cell_id": cid(dk["x_m"].to_numpy(), dk["y_m"].to_numpy()),
            "p": dk["p_boat"],
            "duration_min": np.nan,
            "ship_key": None,
            "matched": False,
        }
    )
    slow = pd.DataFrame(
        {
            "event_id": [f"ev_s_{i:05d}" for i in range(len(ships))],
            "event_type": "slowdown",
            "time_utc": [_day_time(start, v) for v in ships["day"]],
            "x_m": ships["x_m"],
            "y_m": ships["y_m"],
            "cell_id": cid(ships["x_m"].to_numpy(), ships["y_m"].to_numpy()),
            "p": 1.0,
            "duration_min": ships["duration_min"],
            "ship_key": [_ship_key(seed, i) for i in range(len(ships))],
            "matched": True,
        }
    )
    events = pd.concat([dark, slow], ignore_index=True)

    # aggregate/observed: full grid, unobserved rows kept with count 0 and exposure 0
    events["day"] = (
        (events["time_utc"] - pd.Timestamp(start, tz="UTC")).dt.total_seconds() // 86400
    ).astype(int)
    dates = [start + timedelta(days=int(i)) for i in range(days)]
    ex_day = (
        pd.DataFrame(
            {
                "cell_id": exp_df["cell_id"],
                "day": np.repeat(passes["day"].to_numpy(), n),
                "e": exp_df["exposure_small"],
            }
        )
        .groupby(["cell_id", "day"])["e"]
        .sum()
    )
    full = pd.MultiIndex.from_product([cell_ids, range(days)], names=["cell_id", "day"])
    parts = []
    for et in ("dark_small", "slowdown"):
        c = (
            events[events["event_type"] == et]
            .groupby(["cell_id", "day"])["p"]
            .sum()
            .reindex(full, fill_value=0.0)
        )
        e = (
            ex_day.reindex(full, fill_value=0.0)
            if et == "dark_small"
            else pd.Series(
                np.tile(fine["sea_frac"].to_numpy()[:, None], (1, days)).ravel(), index=full
            )
        )
        parts.append(pd.DataFrame({"count": c, "exposure": e, "event_type": et}).reset_index())
    obs = pd.concat(parts, ignore_index=True)
    obs.loc[obs["exposure"] <= 0, "count"] = (
        0.0  # a boat seen in a cell-day with no exposure cannot exist; never store it
    )
    obs["level"] = FINE
    pmap = dict(zip(fine["cell_id"], fine["pcell"], strict=True))
    coarse = (
        obs.assign(cell_id=obs["cell_id"].map(pmap))
        .groupby(["cell_id", "day", "event_type"], as_index=False)[["count", "exposure"]]
        .sum()
    )
    coarse["level"] = COARSE
    observed = pd.concat([obs, coarse], ignore_index=True)
    observed["date"] = [dates[d] for d in observed["day"]]
    observed = observed[["cell_id", "level", "date", "event_type", "count", "exposure"]]

    # forecast/expected: the planted normal rates, Poisson 90% range (phi = 1)
    f = obs.copy()
    ci_ = f["cell_id"].map(dict(zip(cell_ids, range(n), strict=True))).to_numpy()
    # expected soft count of a dark small boat per unit exposure: true rate x P(detected) x mean p_boat (0.75), plus false alarms (p_boat 0.15)
    pdet_day = np.array(
        [
            _p_det(config, np.linspace(*s["small_boat_length_m"], 50), w).mean()
            for w in weather["wind_ms"]
        ]
    )
    small_rate = (
        lam * (0.75 * pdet_day)[:, None] + s["false_alarm_per_km2_pass"] * (FINE / 1000) ** 2 * 0.15
    )
    rate = np.where(
        f["event_type"] == "dark_small", small_rate[f["day"].to_numpy(), ci_], ship_rate[ci_]
    )
    mu = f["exposure"].to_numpy() * rate
    expected = pd.DataFrame(
        {
            "cell_id": f["cell_id"],
            "date": [dates[d] for d in f["day"]],
            "event_type": f["event_type"],
            "mu": mu,
            "phi": 1.0,
            "lo90": poisson.ppf(0.05, mu),
            "hi90": poisson.ppf(0.95, mu),
            "model": "sim_truth",
            "fold": pd.array(
                [0] * len(f), dtype="Int64"
            ),  # the live forecast, as forecast writes it (#172)
        }
    )

    # fuse/cells: observed rows only; mid-p tail, Benjamini-Hochberg at q = 0.1
    seen = f["exposure"].to_numpy() > 0
    ci = np.round(f["count"].to_numpy()[seen])
    pmid = poisson.sf(ci, mu[seen]) + 0.5 * poisson.pmf(ci, mu[seen])
    order = np.argsort(pmid)
    passed = pmid[order] <= 0.1 * (np.arange(1, len(pmid) + 1) / len(pmid))
    bh = np.zeros(len(pmid), bool)
    if passed.any():
        bh[order[: np.flatnonzero(passed).max() + 1]] = True
    u = pd.Series(-pmid).rank(pct=True).to_numpy()
    fc = f[seen]
    fuse_cells = pd.DataFrame(
        {
            "cell_id": fc["cell_id"].to_numpy(),
            "date": [dates[d] for d in fc["day"]],
            "event_type": fc["event_type"].to_numpy(),
            "p_mid": pmid,
            "bh_flag": bh,
            "context": 0.5,
            "U": u,
            "agreement": (u >= 0.9).astype(int),
        }
    )
    c_seen, mu_seen = fc["count"].to_numpy(), mu[seen]
    fuse_cells["y"] = (c_seen + 0.5) / (mu_seen + 0.5)
    week = pd.to_datetime(fuse_cells["date"]).dt.strftime("%G-W%V")
    p6, kind, cid = (
        config["p6"],
        fuse_cells["event_type"].to_numpy(),
        fuse_cells["cell_id"].to_numpy(),
    )
    fuse_cells["gi_z"] = gi_star(cid, kind, week.to_numpy(), c_seen, mu_seen, p6["gi_band_m"])
    fuse_cells["cusum_s"] = cusum(
        cid, kind, fc["day"].to_numpy(), c_seen, mu_seen, p6["cusum_rho"], p6["cusum_h"]
    )
    g = pd.DataFrame(
        {"k": fuse_cells["cell_id"] + fuse_cells["event_type"] + week, "c": c_seen, "m": mu_seen}
    )
    sums = g.groupby("k")[["c", "m"]].transform("sum")
    fuse_cells["y_week"] = ((sums["c"] + 0.5) / (sums["m"] + 0.5)).to_numpy()

    # fuse/sites: one row per planted site (none under `null`), with its pick-ups that no pass could have seen
    pk = boats[boats["kind"] == "pickup"]
    site_cells = list(
        dict.fromkeys(drop_cells.tolist())
    )  # first-drop order; `fixed` has exactly one
    # one link per planted slowdown: L = 1 if a pick-up followed it, aged from its day to T, S = sum L 0.5^(age / h)
    half_life, rows, links = config["p6"]["half_life_days"], [], []
    for j, c in enumerate(site_cells):
        npk_j = int((pick_cells == c).sum())
        dd_c = drop_days[drop_cells == c]
        L_c = np.isin(dd_c, picked).astype(float)
        age_c = np.clip(days - 1 - dd_c, 0, None)
        S_c = float((L_c * 0.5 ** (age_c / half_life)).sum())
        links.append(pd.DataFrame({"site_id": str(cell_ids[c]), "L": L_c, "age_days": age_c}))
        seen_j = int((pk["cell"] == c).mul(pk["pass"].ge(0)).sum())
        dist = np.hypot(piers["geometry"].x - ccx[c], piers["geometry"].y - ccy[c])
        top = piers.assign(d=dist)[piers["road_access"]].nsmallest(2, "d")["pier_id"].tolist()
        rows.append(
            {
                "site_id": str(cell_ids[c]),  # R1: site_id = cell_id (A2), as in truth and fuse
                "x_m": ccx[c],
                "y_m": ccy[c],
                "n_slowdowns": int((drop_cells == c).sum()),
                "S": S_c,
                "p_perm": 0.01,
                "bh_flag": True,
                "recurrence": npk_j,
                "followup_unobserved": npk_j - seen_j,
                "agreement": 4,
                "reasons": ["planted drop site (simulated)"],
                "top_piers": top,
            }
        )
    # stand-in sites (#104): rows with no drops in truth, so patrol and the dashboard have 16+ sites to rank and route.
    # Planted sites stay first and above every stand-in on S; no stand-ins under `null`. Values are stand-ins, not
    # statistics: S falls by rank below the lowest planted S, a quarter are flagged, agreement and follow-ups vary.
    n_in = s["stand_in_sites"] if rows else 0
    pool = np.flatnonzero(
        ok
    )  # the planted site's candidates: 5-20 km out, off the lane, exclusion and wind farm
    chosen = list(site_cells)
    for c in _rng(config, "sites", seed).permutation(pool):
        if len(chosen) == len(site_cells) + n_in:
            break
        if np.hypot(ccx[c] - ccx[chosen], ccy[c] - ccy[chosen]).min() > s["site_gap_m"]:
            chosen.append(int(c))
    low = min(r["S"] for r in rows) if rows else 0.0
    for k, c in enumerate(chosen[len(site_cells) :], start=1):
        S_k = low * (n_in + 1 - k) / (n_in + 1)
        m = int(np.ceil(S_k))
        links.append(
            pd.DataFrame(
                {"site_id": [str(cell_ids[c])] * m, "L": [S_k / max(m, 1)] * m, "age_days": 0.0}
            )
        )
        dist = np.hypot(piers["geometry"].x - ccx[c], piers["geometry"].y - ccy[c])
        top = piers.assign(d=dist)[piers["road_access"]].nsmallest(2, "d")["pier_id"].tolist()
        rec = n_in + 1 - k
        rows.append(
            {
                "site_id": str(cell_ids[c]),
                "x_m": ccx[c],
                "y_m": ccy[c],
                "n_slowdowns": rec,
                "S": S_k,
                "p_perm": k / (n_in + 1),
                "bh_flag": k <= n_in // 4,
                "recurrence": rec,
                "followup_unobserved": rec * (k % 2),
                "agreement": (n_in - k) % 5,
                "reasons": ["stand-in site (simulated, no planted drops)"],
                "top_piers": top,
            }
        )
    site_cells = chosen
    sites = pd.DataFrame(rows, columns=SITE_COLS).astype(
        {
            "x_m": float,
            "y_m": float,
            "n_slowdowns": int,
            "S": float,
            "p_perm": float,
            "bh_flag": bool,
        }
        | {"recurrence": int, "followup_unobserved": int, "agreement": int}
    )  # typed even when `null` leaves it empty

    # reference/travel_hours: straight-line distance at the simulated boat speed
    cx, cy = x0 + (fine["ix"].to_numpy() + 0.5) * FINE, y0 + (fine["iy"].to_numpy() + 0.5) * FINE
    px, py = piers["geometry"].x.to_numpy(), piers["geometry"].y.to_numpy()
    d = np.hypot(cx[:, None] - px[None, :], cy[:, None] - py[None, :])
    travel = pd.DataFrame(
        {
            "cell_id": np.repeat(cell_ids, 6),
            "pier_id": np.tile(piers["pier_id"].to_numpy(), n),
            "hours": (d / (s["boat_speed_kn"] * KN) / 3600).ravel(),
        }
    )

    # fuse/piers: P_j = sum of S x exp(-T / 1 h) over the planted sites
    P_j = np.zeros(len(piers))
    for c, S in zip(site_cells, sites["S"], strict=True):
        t_site = travel[travel["cell_id"] == cell_ids[c]].set_index("pier_id")["hours"]
        P_j = P_j + S * np.exp(-t_site.reindex(piers["pier_id"]).to_numpy())
    fuse_piers = pd.DataFrame({"pier_id": piers["pier_id"], "P_j": P_j})
    fuse_links = (
        pd.concat(links, ignore_index=True)
        if links
        else pd.DataFrame({"site_id": pd.Series([], dtype=object), "L": [], "age_days": []})
    )

    # coverage/weather_daily (#208): the weather is uniform and constant through each day, so the daily max is the
    # day's value in every cell; float32 as sim/raw.py stores it in era5.nc
    weather_daily = pd.DataFrame(
        {
            "cell_id": np.tile(cell_ids, days),
            "date": np.repeat([start + timedelta(days=d) for d in range(days)], n),
            "wind_max_ms": np.repeat(weather["wind_ms"].to_numpy(np.float32), n).astype(float),
            "hs_max_m": np.repeat(weather["hs_m"].to_numpy(np.float32), n).astype(float),
        }
    )

    for name, frame in {
        "reference/cells": gpd.GeoDataFrame(cells, crs=32629),
        "reference/piers": piers,
        "reference/land": gpd.GeoDataFrame(  # north of the shore line, as raw/coastline.gpkg draws it
            {"id": [0]},
            geometry=[box(x0, y0 + (NY - 1 + SHORE_FRAC) * FINE, x0 + NX * FINE, y0 + NY * FINE)],
            crs=32629,
        ),
        "reference/travel_hours": travel,
        "coverage/exposure": exp_df,
        "coverage/weather_daily": weather_daily,
        "detect/detections": detections,
        "match/events": events.drop(columns="day"),
        "aggregate/observed": observed,
        "forecast/expected": expected,
        "fuse/cells": fuse_cells,
        "fuse/sites": sites,
        "fuse/piers": fuse_piers,
        "fuse/links": fuse_links,
    }.items():
        io.write_stage(name, frame, "simulated")

    last = (start + timedelta(days=days - 1)).isoformat()  # the simulator has no feed lag
    io.write_snapshot(
        {"latest": {"radar": last, "gfw_presence": last, "gfw_sar": last, "era5": last}}
    )

    world = SimWorld(config, seed, start, days, fine, weather, passes, boats, ships, detections)
    write_scenes(world)
    write_static(world)
    write_raw(world)  # last: the manifest lists every file the others wrote

    # truth: every true boat, every planted drop and pick-up. Only validate reads it.
    tb = boats.assign(
        time_utc=[_day_time(start, v) for v in boats["day"]],
        cell_id=cell_ids[boats["cell"].to_numpy()],
        pass_index=boats["pass"],
    )

    # learning layer (docs/learning.md L1): the regime on every row; per drop its site_id (= cell_id, as fuse/sites
    # under A2), time_utc and active (a drop that happened); under `displacing`, the simulator's own patrol visits
    def planted(kind: str, when: np.ndarray, at: np.ndarray, active: bool) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "kind": kind,
                "time_utc": pd.Series(
                    [_day_time(start, v) for v in when], dtype="datetime64[ns, UTC]"
                ),
                "x_m": ccx[at],
                "y_m": ccy[at],
                "cell_id": cell_ids[at],
                "length_m": np.nan,
                "detected": False,
                "pass_index": -1,
                "site_id": cell_ids[at],
                "active": active,
            }
        )

    truth = pd.concat(
        [
            tb[
                ["kind", "time_utc", "x_m", "y_m", "cell_id", "length_m", "detected", "pass_index"]
            ].assign(site_id=None, active=False),
            planted("drop", drop_days, drop_cells, True),
            *([planted("visit", visit_days, visit_cells, False)] if len(visit_days) else []),
        ],
        ignore_index=True,
    ).assign(regime=regime)
    out = io.truth_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    truth.to_parquet(out, index=False)
