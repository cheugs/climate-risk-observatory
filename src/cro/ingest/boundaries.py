"""Download admin-1 boundaries (states, provinces, regions) from geoBoundaries.

Why geoBoundaries: it is open (CC-BY 4.0), covers almost every country, and
uses a consistent admin-1 definition. That is exactly what we need to compare
regions across countries.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import affinity
from shapely.geometry import box
from shapely.ops import unary_union

from cro.config import load_config
from cro.utils import get_json, log, save_table

# The geoBoundaries API address. Adding /{ISO3}/ADM1/ returns one country.
API = "https://www.geoboundaries.org/api/current/gbOpen"


def get_country_metadata(iso3: str) -> dict:
    """Ask the API where the ADM1 file for one country lives."""
    data = get_json(f"{API}/{iso3}/ADM1/")
    # For one country the API returns a dict, for "ALL" it returns a list.
    if isinstance(data, list):
        data = data[0]
    return data


def fix_antimeridian(geometry):
    """Make polygons that cross the 180 degree line valid.

    Alaska is the classic example: its islands sit on both sides of the
    date line, so a naive polygon appears to stretch around the whole world.
    We move all longitudes into 0-360, split at 180, then move the eastern
    piece back to -180..0. Small polygons are returned unchanged.
    """
    if geometry is None or geometry.is_empty:
        return geometry

    minx, _, maxx, _ = geometry.bounds
    if maxx - minx <= 180:
        # Normal polygon: nothing to fix.
        return geometry

    # Work in a 0-360 frame where the crossing is continuous.
    moved = affinity.translate(geometry, xoff=0)
    moved = _shift_lons(moved, lambda x: x % 360)

    west = moved.intersection(box(0, -90, 180, 90))
    east = moved.intersection(box(180, -90, 360, 90))
    east = _shift_lons(east, lambda x: x - 360) if not east.is_empty else east

    pieces = [p for p in (west, east) if p is not None and not p.is_empty]
    if not pieces:
        return geometry
    return unary_union(pieces)


def _shift_lons(geometry, func):
    """Apply a longitude transformation to every coordinate."""
    from shapely.ops import transform

    return transform(lambda x, y, z=None: (func(x), y), geometry)


def standardise_boundaries(gdf: gpd.GeoDataFrame, iso3: str, meta: dict) -> gpd.GeoDataFrame:
    """Keep the columns we need and give them clear names."""
    # geoBoundaries stores most information in the GeoJSON properties.
    # The exact names are stable but we provide fallbacks just in case.
    props = gdf.columns

    def pick(*names, default=None):
        for name in names:
            if name in props:
                return gdf[name]
        return default

    shape_id = pick("shapeID", "shapeId")
    name = pick("shapeName", "shape_name")
    region_type = pick("shapeType", "shape_type")

    out = gpd.GeoDataFrame(
        {
            "region_id": iso3 + "-" + shape_id.astype(str),
            "iso3": iso3,
            "country": meta.get("boundaryName", iso3),
            "region_name": name.astype(str),
            "region_type": region_type.astype(str) if region_type is not None else None,
            "geometry": gdf.geometry.values,
        },
        crs="EPSG:4326",
    )

    # Invalid geometries (self-intersections, duplicate points) break spatial
    # joins. make_valid repairs them without dropping the region.
    out["geometry"] = out.geometry.make_valid()
    out = out[~out.geometry.is_empty & out.geometry.notna()].copy()

    # Area is calculated in an equal-area projection, not in degrees.
    # EPSG:6933 is an equal-area projection that works for the whole world.
    out["area_km2"] = out.to_crs(6933).area / 1_000_000

    # A representative point always falls inside the polygon (a normal
    # centroid can fall outside a curved shape such as a coastal region).
    points = out.geometry.representative_point()
    out["centroid_lon"] = points.x
    out["centroid_lat"] = points.y

    return out


def load_regions(iso3_list: list[str], use_simplified: bool = False) -> gpd.GeoDataFrame:
    """Download and stack ADM1 boundaries for several countries."""
    frames = []
    for iso3 in iso3_list:
        log(f"boundaries: {iso3}")
        meta = get_country_metadata(iso3)
        url = meta["simplifiedGeometryGeoJSON"] if use_simplified else meta["gjDownloadURL"]

        # geopandas can read a remote GeoJSON directly.
        gdf = gpd.read_file(url)
        gdf = standardise_boundaries(gdf, iso3, meta)
        gdf["geometry"] = gdf.geometry.apply(fix_antimeridian)
        frames.append(gdf)

    regions = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")

    # Small islands sometimes come back as points after simplification.
    # We keep only polygon geometries for the analysis.
    regions = regions[regions.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    regions["region_id"] = regions["region_id"].astype(str)
    regions = regions.drop_duplicates("region_id").reset_index(drop=True)

    # Some regions are very far from the rest of their country (Alaska,
    # Hawaii, Puerto Rico, the Canary Islands...). We mark them so the
    # analysis can test whether they change the results.
    regions["is_remote"] = False
    for iso3, group in regions.groupby("iso3"):
        # The "typical" location is the median centroid of the country.
        median_lon = group["centroid_lon"].median()
        median_lat = group["centroid_lat"].median()
        distance = _haversine_km(median_lat, median_lon,
                                 group["centroid_lat"], group["centroid_lon"])
        regions.loc[group.index, "is_remote"] = distance > 3000

    log(f"boundaries: {len(regions)} regions in {regions['iso3'].nunique()} countries")
    return regions


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km. Works with single values or Series."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def run(iso3_list: list[str] | None = None) -> gpd.GeoDataFrame:
    """Download the pilot boundaries and save them to data/processed."""
    cfg = load_config()
    iso3_list = iso3_list or cfg["project"]["pilot_iso3"]

    regions = load_regions(iso3_list)

    # GeoParquet keeps the geometry and is fast to reload.
    out_path = Path(cfg["paths"]["processed"]) / "regions.parquet"
    save_table(regions, out_path)

    # A GeoPackage is easier to open in QGIS if someone wants to check the map.
    gpkg_path = Path(cfg["paths"]["processed"]) / "regions.gpkg"
    regions.to_file(gpkg_path, driver="GPKG")
    log(f"boundaries: wrote {gpkg_path.name}")

    # Also save a small CSV with the attributes (no geometry) for quick checks.
    attrs = pd.DataFrame(regions.drop(columns="geometry"))
    attrs.to_csv(Path(cfg["paths"]["processed"]) / "regions_attributes.csv", index=False)

    return regions


if __name__ == "__main__":
    run()
