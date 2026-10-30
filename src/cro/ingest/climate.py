"""Daily climate data from NASA POWER.

Why NASA POWER instead of Open-Meteo?
- Open-Meteo is excellent, but its free tier limits how much data one can
  download per minute, and 33 years of daily data for thousands of points
  hits that limit quickly.
- NASA POWER gives the same kind of daily data (MERRA-2 reanalysis) with a
  simple point API, no key, and a generous limit.

The idea, in plain words:
1. Put a small number of sample points inside every region.
2. Download daily maximum temperature, minimum temperature and rainfall
   for each sample point from 1991 to 2023.
3. Turn the daily values into yearly hazard indicators (heat days, dry
   spells, heavy rain...).
4. Average the points inside each region.

We use a few points per region, not one: a large region such as Alaska has
very different climates in the north and the south. The number of points
grows with the size of the region, up to a maximum.
"""

from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests

from cro.config import load_config
from cro.utils import log, save_table

NASA_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

# NASA parameter name -> our column name.
# T2M_MAX = daily maximum temperature at 2 m (C)
# T2M_MIN = daily minimum temperature at 2 m (C)
# PRECTOTCORR = corrected total precipitation (mm/day)
PARAMETERS = {
    "T2M_MAX": "tmax",
    "T2M_MIN": "tmin",
    "PRECTOTCORR": "precip",
}

FILL_VALUE = -999.0


# ---------------------------------------------------------------------------
# 1. Choose sample points inside each region
# ---------------------------------------------------------------------------

def build_sample_points(regions: gpd.GeoDataFrame, cfg: dict) -> gpd.GeoDataFrame:
    """Pick evenly spread points inside every region.

    We start from a 1 degree grid, then keep at most `max_points_per_region`
    of them. The points are chosen with "farthest point sampling": always
    take the point that is furthest from the points already chosen. This
    spreads them across the region instead of clustering them.
    """
    step = cfg["climate"]["grid_degrees"]
    max_points = cfg["climate"]["max_points_per_region"]
    area_per_point = cfg["climate"]["area_per_point_km2"]

    rows = []
    for region in regions.itertuples():
        # How many points does this region deserve? Large regions get more.
        n_points = int(np.clip(round(region.area_km2 / area_per_point), 1, max_points))

        candidates = _grid_points_in_polygon(region.geometry, step)
        if len(candidates) == 0:
            # Small island: use the representative point.
            point = region.geometry.representative_point()
            candidates = np.array([[point.x, point.y]])
        if len(candidates) > n_points:
            candidates = _farthest_point_sample(candidates, n_points)

        for lon, lat in candidates:
            rows.append({
                "region_id": region.region_id,
                "iso3": region.iso3,
                "lon": float(lon),
                "lat": float(lat),
                # Weight used when averaging points inside a region:
                # a point close to the poles covers fewer km2.
                "area_weight_km2": (step * 111.32) ** 2 * np.cos(np.radians(lat)),
            })

    points = gpd.GeoDataFrame(
        rows,
        geometry=gpd.points_from_xy([r["lon"] for r in rows], [r["lat"] for r in rows]),
        crs="EPSG:4326",
    )
    points["point_id"] = points["iso3"] + "_" + points.index.astype(str)

    log(f"climate: {len(points)} sample points in {len(regions)} regions")
    return points


def _grid_points_in_polygon(polygon, step: float) -> np.ndarray:
    """All grid cell centres of a 1 degree lattice that fall inside a polygon."""
    if polygon is None or polygon.is_empty:
        return np.empty((0, 2))

    minx, miny, maxx, maxy = polygon.bounds
    lons = np.arange(np.floor(minx), np.ceil(maxx) + step, step) + step / 2
    lats = np.arange(np.floor(miny), np.ceil(maxy) + step, step) + step / 2

    from shapely.geometry import Point
    from shapely import contains

    pts = []
    for lon, lat in itertools.product(lons, lats):
        point = Point(lon, lat)
        if contains(polygon, point):
            pts.append((lon, lat))

    return np.array(pts) if pts else np.empty((0, 2))


def _farthest_point_sample(points: np.ndarray, n: int) -> np.ndarray:
    """Choose `n` points that are as spread out as possible.

    Start with the point closest to the mean centre, then repeatedly add the
    point whose distance to the nearest chosen point is largest.
    """
    centre = points.mean(axis=0)
    distances = np.linalg.norm(points - centre, axis=1)
    chosen = [int(np.argmin(distances))]

    while len(chosen) < n:
        # Distance from every point to the closest chosen point.
        closest = np.min(
            np.linalg.norm(points[:, None, :] - points[chosen][None, :, :], axis=2),
            axis=1,
        )
        closest[chosen] = -1  # do not pick the same point twice
        chosen.append(int(np.argmax(closest)))

    return points[chosen]


# ---------------------------------------------------------------------------
# 2. Download daily data for one point
# ---------------------------------------------------------------------------

def fetch_point(lon: float, lat: float, start: str, end: str, retries: int = 5) -> pd.DataFrame:
    """Download one daily time series and return a clean DataFrame."""
    params = {
        "parameters": ",".join(PARAMETERS),
        "community": "AG",
        "longitude": round(lon, 3),
        "latitude": round(lat, 3),
        "start": start,
        "end": end,
        "format": "JSON",
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(NASA_URL, params=params, timeout=180)
            if response.status_code == 200:
                break
            # 429 = too many requests; 5xx = server problem. Both are temporary.
            if response.status_code == 429 or response.status_code >= 500:
                import time
                time.sleep(2 * attempt)
                continue
            response.raise_for_status()
        except requests.RequestException:
            import time
            time.sleep(2 * attempt)
    else:
        raise RuntimeError(f"NASA POWER failed for {lat},{lon}")

    payload = response.json()["properties"]["parameter"]

    # The API returns {"YYYYMMDD": value}. Turn it into a normal table.
    dates = pd.to_datetime(list(payload["T2M_MAX"].keys()), format="%Y%m%d")
    frame = pd.DataFrame({"date": dates})
    for nasa_name, our_name in PARAMETERS.items():
        values = np.array([payload[nasa_name][d] for d in payload[nasa_name]], dtype=float)
        # -999 means "no data" in NASA POWER.
        values[values <= FILL_VALUE + 1] = np.nan
        frame[our_name] = values

    return frame


def download_points(points: gpd.GeoDataFrame, cfg: dict) -> pd.DataFrame:
    """Download every point, using the cache when possible.

    Requests are sent in parallel (4 at a time by default) because each
    request is small. The cache means an interrupted download can resume.
    """
    cache_dir = Path(cfg["paths"]["cache"]) / "climate"
    cache_dir.mkdir(parents=True, exist_ok=True)

    start = cfg["climate"]["history_start"].replace("-", "")
    end = cfg["climate"]["history_end"].replace("-", "")

    def load_or_download(row) -> pd.DataFrame:
        cache_file = cache_dir / f"power_{row.lat:.3f}_{row.lon:.3f}_{start}_{end}.parquet"
        if cache_file.exists():
            daily = pd.read_parquet(cache_file)
        else:
            daily = fetch_point(row.lon, row.lat, start, end)
            daily.to_parquet(cache_file, index=False)
        daily["point_id"] = row.point_id
        return daily

    frames = []
    workers = cfg["climate"]["workers"]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(load_or_download, row): row for row in points.itertuples()}
        for i, future in enumerate(as_completed(futures), start=1):
            row = futures[future]
            try:
                frames.append(future.result())
            except Exception as error:
                log(f"climate: point {row.point_id} failed ({error})")
            if i % 25 == 0 or i == len(futures):
                log(f"climate: {i}/{len(futures)} points downloaded")

    if not frames:
        raise RuntimeError("No climate data was downloaded")

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 3. Daily data -> yearly indicators
# ---------------------------------------------------------------------------

def hargreaves_et0(tmax: np.ndarray, tmin: np.ndarray, lat: float,
                   day_of_year: np.ndarray) -> np.ndarray:
    """Estimate reference evapotranspiration with the Hargreaves formula.

    NASA POWER does not provide ET0 directly, so we calculate a standard
    estimate from temperature and latitude. This is the same idea used by
    irrigation engineers: warm, sunny places evaporate more water.
    """
    phi = np.radians(lat)
    dr = 1 + 0.033 * np.cos(2 * np.pi * day_of_year / 365)
    decl = 0.409 * np.sin(2 * np.pi * day_of_year / 365 - 1.39)
    # Clip avoids invalid arccos values during polar day/night.
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(decl), -1, 1))

    ra_mj = (24 * 60 / np.pi) * 0.0820 * dr * (
        ws * np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.sin(ws)
    )
    ra_mm = ra_mj * 0.408  # convert MJ/m2/day to mm/day equivalent

    tmean = (tmax + tmin) / 2
    td = np.clip(tmax - tmin, 0, None)
    et0 = 0.0023 * ra_mm * (tmean + 17.8) * np.sqrt(td)
    return np.clip(et0, 0, None)


def longest_dry_spell(precip: np.ndarray, threshold: float) -> int:
    """Length of the longest run of days with rainfall below `threshold`."""
    dry = precip < threshold
    if not dry.any():
        return 0
    padded = np.concatenate(([False], dry, [False])).astype(int)
    changes = np.diff(padded)
    starts = np.where(changes == 1)[0]
    ends = np.where(changes == -1)[0]
    return int((ends - starts).max())


def compute_annual_indicators(daily: pd.DataFrame, cfg: dict, lat: float) -> pd.DataFrame:
    """Turn daily records into one row per point per year."""
    if daily.empty:
        return pd.DataFrame()

    climate_cfg = cfg["climate"]
    daily = daily.copy()
    daily["year"] = daily["date"].dt.year
    daily["doy"] = daily["date"].dt.dayofyear
    daily["et0"] = hargreaves_et0(daily["tmax"].to_numpy(), daily["tmin"].to_numpy(),
                                  lat, daily["doy"].to_numpy())

    rows = []
    for (point_id, year), group in daily.groupby(["point_id", "year"], sort=False):
        group = group.sort_values("date")
        tmax = group["tmax"].to_numpy(dtype=float)
        tmin = group["tmin"].to_numpy(dtype=float)
        precip = np.nan_to_num(group["precip"].to_numpy(dtype=float))
        et0 = np.nan_to_num(group["et0"].to_numpy(dtype=float))

        # A year with too many missing days would give a misleading value.
        if np.isnan(tmax).sum() > 60:
            continue

        rows.append({
            "point_id": point_id,
            "year": int(year),
            "hd35": float(np.nansum(tmax >= climate_cfg["heat_threshold_c"])),
            "tr25": float(np.nansum(tmin >= climate_cfg["tropical_night_c"])),
            "cdd": float(longest_dry_spell(precip, climate_cfg["dry_day_mm"])),
            "p_sum": float(np.nansum(precip)),
            "et0_sum": float(np.nansum(et0)),
            "wbal": float(np.nansum(precip) - np.nansum(et0)),
            "rx1d": float(np.nanmax(precip)) if len(precip) else np.nan,
            "r50": float(np.nansum(precip > climate_cfg["wet_day_mm"])),
        })

    return pd.DataFrame(rows)


def add_trends(annual: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Add the 1991-2023 trend in heat days (days per decade) per point."""
    from scipy.stats import linregress

    start, end = cfg["climate"]["trend_start"], cfg["climate"]["trend_end"]
    window = annual[(annual["year"] >= start) & (annual["year"] <= end)]

    trends = []
    for point_id, group in window.groupby("point_id"):
        group = group.dropna(subset=["hd35"])
        if len(group) < 10:
            continue
        slope = linregress(group["year"], group["hd35"]).slope
        trends.append({"point_id": point_id, "hd35_trend": slope * 10})

    trend_df = pd.DataFrame(trends)
    return annual.merge(trend_df, on="point_id", how="left")


# ---------------------------------------------------------------------------
# 4. Point values -> region values
# ---------------------------------------------------------------------------

def summarise_by_region(annual: pd.DataFrame, points: pd.DataFrame,
                        population: pd.DataFrame | None, cfg: dict) -> pd.DataFrame:
    """Average point indicators inside each region.

    Two averages are produced:
    - area weighted: every km2 counts the same (describes the climate)
    - population weighted: every person counts the same (describes what
      people actually experience)
    """
    indicators = ["hd35", "tr25", "cdd", "wbal", "rx1d", "r50", "p_sum"]

    baseline = annual[
        (annual["year"] >= cfg["climate"]["baseline_start"])
        & (annual["year"] <= cfg["climate"]["baseline_end"])
    ].groupby("point_id")[indicators].mean().reset_index()

    data = points[["point_id", "region_id", "area_weight_km2"]].merge(
        baseline, on="point_id", how="inner"
    )
    trend = annual.groupby("point_id")["hd35_trend"].mean().reset_index()
    data = data.merge(trend, on="point_id", how="left")

    if population is not None and not population.empty:
        data = data.merge(population[["point_id", "point_pop"]], on="point_id", how="left")
    else:
        data["point_pop"] = np.nan

    rows = []
    for region_id, group in data.groupby("region_id"):
        row = {"region_id": region_id, "n_points": len(group)}

        for indicator in indicators:
            row[f"{indicator}_area"] = _weighted(group[indicator], group["area_weight_km2"])
            row[f"{indicator}_pop"] = _weighted(group[indicator], group["point_pop"])
        row["hd35_trend_area"] = _weighted(group["hd35_trend"], group["area_weight_km2"])

        rows.append(row)

    return pd.DataFrame(rows)


def _weighted(values: pd.Series, weights: pd.Series) -> float:
    """Weighted mean that returns NaN when no weights are available."""
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return np.nan
    return float(np.average(values[mask], weights=weights[mask]))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_points(regions_path: Path | None = None) -> gpd.GeoDataFrame:
    """Build and save the sample points (step 1 of the climate work)."""
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    regions = gpd.read_parquet(regions_path or processed / "regions.parquet")

    points = build_sample_points(regions, cfg)
    save_table(points, processed / "climate_points.parquet")
    return points


def run(regions_path: Path | None = None) -> pd.DataFrame:
    """Full climate step: sample points -> download -> yearly -> regions."""
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])

    points_path = processed / "climate_points.parquet"
    if points_path.exists():
        # Reuse the points created by `cro climate-points` so that the
        # population step can attach population to the same points.
        points = gpd.read_parquet(points_path)
    else:
        points = build_points(regions_path)

    daily = download_points(points, cfg)

    # Compute yearly indicators point by point (latitude is needed for ET0).
    lat_by_point = dict(zip(points["point_id"], points["lat"]))
    yearly = []
    for point_id, group in daily.groupby("point_id"):
        yearly.append(compute_annual_indicators(
            group, cfg, lat_by_point[point_id]
        ))

    annual = pd.concat(yearly, ignore_index=True)
    annual = add_trends(annual, cfg)

    # Population per point is created by the population step.
    pop_path = processed / "point_population.parquet"
    point_pop = pd.read_parquet(pop_path) if pop_path.exists() else None

    region_climate = summarise_by_region(annual, points, point_pop, cfg)

    save_table(points, processed / "climate_points.parquet")
    save_table(annual, processed / "climate_point_year.parquet")
    save_table(region_climate, processed / "climate_regions.parquet")

    return region_climate


if __name__ == "__main__":
    run()
