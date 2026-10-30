"""Population counts from GHS-POP (Global Human Settlement Layer).

GHS-POP gives the number of people in every 30 arc-second cell (about
1 km at the equator) for the year 2020. We use it for two things:

1. the total population of each region, and
2. the population of each 1 degree climate grid cell, which lets us build
   exposure measures such as "person-days above 35 C".
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.mask import mask as raster_mask
from rasterio.transform import Affine
from rasterio.windows import from_bounds

from cro.config import load_config
from cro.utils import log, save_table

ZIP_NAME = "GHS_POP_E2020.zip"


def extract_raster(cfg: dict) -> Path:
    """Unzip the GHS-POP archive once and return the .tif path."""
    raw_dir = Path(cfg["paths"]["raw"])
    zip_path = raw_dir / ZIP_NAME
    out_dir = raw_dir / "ghs_pop"
    out_dir.mkdir(parents=True, exist_ok=True)

    tif_files = list(out_dir.glob("*.tif"))
    if tif_files:
        return tif_files[0]

    if not zip_path.exists():
        raise FileNotFoundError(
            f"{zip_path} is missing. Download it from the GHSL website and put it in data/raw/."
        )

    log("population: unzipping GHS-POP (this happens only once)")
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            if member.endswith(".tif"):
                archive.extract(member, out_dir)

    tif_files = list(out_dir.glob("*.tif"))
    if not tif_files:
        raise FileNotFoundError("No .tif file found inside the GHS-POP archive")
    return tif_files[0]


def region_population(regions: gpd.GeoDataFrame, raster_path: Path) -> pd.DataFrame:
    """Sum the population raster inside every region polygon."""
    rows = []
    with rasterio.open(raster_path) as src:
        for region in regions.itertuples():
            try:
                # crop=True keeps only the pixels around the polygon, which
                # is much faster than reading the whole world for each region.
                data, _ = raster_mask(src, [region.geometry], crop=True, filled=False)
                values = data[0]
                # Masked pixels (ocean, no data) are ignored.
                valid = values.compressed() if hasattr(values, "compressed") else values.ravel()
                valid = valid[np.isfinite(valid)]
                population = float(np.nansum(valid))
            except Exception as error:
                log(f"population: {region.region_id} failed ({error})")
                population = np.nan

            rows.append({
                "region_id": region.region_id,
                "population": population,
                "population_2020": population,
            })

    df = pd.DataFrame(rows)
    df["area_km2"] = regions.set_index("region_id").loc[df["region_id"], "area_km2"].values
    df["pop_density"] = df["population"] / df["area_km2"].replace(0, np.nan)
    return df


def point_population(points: gpd.GeoDataFrame, regions: gpd.GeoDataFrame,
                     raster_path: Path, downsample: int = 12) -> pd.DataFrame:
    """Assign every person in a region to the nearest climate sample point.

    A simple 0.5 degree box around each point misses most people, because
    regions are much bigger than that box. Instead we divide each region
    into "nearest point" areas (a Voronoi split): every population pixel
    belongs to the sample point that is closest to it.

    To keep this fast we read the population raster at a coarser resolution
    (every 12th pixel, about 0.1 degrees). That is plenty accurate for
    weights and much quicker than working with 1 km pixels.
    """
    totals = {point_id: 0.0 for point_id in points["point_id"]}

    with rasterio.open(raster_path) as src:
        for region in regions.itertuples():
            region_points = points[points["region_id"] == region.region_id]
            if region_points.empty:
                continue

            # Work only on the part of the world that contains this region.
            window = from_bounds(*region.geometry.bounds, transform=src.transform)
            window = window.round_offsets().round_lengths()

            height = max(1, int(window.height / downsample))
            width = max(1, int(window.width / downsample))

            try:
                data = src.read(1, window=window, out_shape=(height, width), masked=True)
            except Exception as error:
                log(f"population: could not read {region.region_id} ({error})")
                continue

            # The transform of the coarser window, needed to place pixels.
            # scale_x/scale_y say how many original pixels one coarse pixel covers.
            scale_x = window.width / width
            scale_y = window.height / height
            coarse_transform = src.window_transform(window) * Affine.scale(scale_x, scale_y)
            inside = geometry_mask([region.geometry], out_shape=(height, width),
                                   transform=coarse_transform, invert=True)

            values = np.ma.filled(data, 0.0).astype(float)
            values = np.where(inside, values, 0.0)
            values[values < 0] = 0.0  # GHS-POP uses negative values for no data

            # Reading a coarse window averages the original pixels, so each
            # coarse value is "people per 1 km pixel". Multiplying by the
            # number of original pixels per coarse pixel restores the total
            # number of people.
            values = values * (scale_x * scale_y)

            rows, cols = np.where(values > 0)
            if len(rows) == 0:
                continue

            # Pixel centres in lon/lat.
            xs, ys = rasterio.transform.xy(coarse_transform, rows, cols, offset="center")
            xs = np.array(xs)
            ys = np.array(ys)

            # Convert degrees to approximate kilometres so that distance is
            # not distorted near the poles.
            mean_lat = np.radians(np.mean(ys))
            px = (xs - xs.mean()) * 111.32 * np.cos(mean_lat)
            py = (ys - ys.mean()) * 110.57

            pxs = (region_points["lon"].to_numpy() - xs.mean()) * 111.32 * np.cos(mean_lat)
            pys = (region_points["lat"].to_numpy() - ys.mean()) * 110.57

            # Distance from every populated pixel to every sample point.
            distances = (px[:, None] - pxs[None, :]) ** 2 + (py[:, None] - pys[None, :]) ** 2
            nearest = np.argmin(distances, axis=1)

            population = values[rows, cols]
            point_ids = region_points["point_id"].to_numpy()

            for index, point_id in enumerate(point_ids):
                totals[point_id] += float(population[nearest == index].sum())

    return pd.DataFrame({"point_id": list(totals), "point_pop": list(totals.values())})


def run() -> pd.DataFrame:
    """Create region and point population tables."""
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])

    regions = gpd.read_parquet(processed / "regions.parquet")
    points = gpd.read_parquet(processed / "climate_points.parquet")

    raster_path = extract_raster(cfg)
    log(f"population: using {raster_path.name}")

    regions_pop = region_population(regions, raster_path)
    save_table(regions_pop, processed / "population_regions.parquet")

    # Every person is assigned to the nearest climate point.
    points_pop = point_population(points, regions, raster_path)
    save_table(points_pop, processed / "point_population.parquet")

    # A quick check: the two ways of counting people should agree.
    region_total = regions_pop["population"].sum()
    point_total = points_pop["point_pop"].sum()
    log(f"population: region total {region_total / 1e6:.1f}M vs point total {point_total / 1e6:.1f}M")

    return regions_pop


if __name__ == "__main__":
    run()
