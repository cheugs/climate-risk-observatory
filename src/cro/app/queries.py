"""Data access for the dashboard.

The app prefers PostGIS (the "proper" store) and falls back to the Parquet
files if the database is not running. This means a reader who clones the
repository can start the dashboard without installing a database.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd

from cro.config import database_url, load_config
from cro.utils import log


def _from_database(cfg: dict) -> gpd.GeoDataFrame | None:
    """Try PostGIS first."""
    try:
        from sqlalchemy import create_engine

        engine = create_engine(database_url(cfg), pool_pre_ping=True)
        query = """
            SELECT v.*, r.geom
            FROM vw_region_profile v
            JOIN dim_region r ON r.region_id = v.region_id
        """
        gdf = gpd.read_postgis(query, engine, geom_col="geom")
        if len(gdf):
            # PostGIS calls the column "geom"; the Parquet fallback calls it
            # "geometry". Use one name everywhere so the two paths behave the
            # same and no stray bytes column leaks into the GeoJSON.
            gdf = gdf.rename_geometry("geometry")
            log("dashboard: loaded data from PostGIS")
            return gdf
    except Exception as error:
        log(f"dashboard: PostGIS unavailable ({str(error)[:80]}), using Parquet")
    return None


def _from_parquet(cfg: dict) -> gpd.GeoDataFrame:
    """Fallback: read the files the pipeline wrote."""
    processed = Path(cfg["paths"]["processed"])
    master = pd.read_parquet(processed / "region_master.parquet")
    regions = gpd.read_parquet(processed / "regions.parquet")

    gdf = regions[["region_id", "geometry"]].merge(master, on="region_id", how="left")
    return gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")


def load_data() -> gpd.GeoDataFrame:
    """Load the region table and simplify the geometry for the browser."""
    from cro.utils import load_geo_table

    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    cache = processed / "dashboard_regions.parquet"
    master_path = processed / "region_master.parquet"

    # Reading full-detail boundaries from PostGIS and simplifying them takes
    # around 20 seconds. The dashboard only needs a light copy, so we save it
    # once and reuse it until the analysis table changes. When the master
    # table is absent (a deployment that ships only the cache), the cache is
    # the best data we have, so use it.
    cache_is_fresh = cache.exists() and (
        not master_path.exists()
        or cache.stat().st_mtime >= master_path.stat().st_mtime
    )
    if cache_is_fresh:
        log("dashboard: loaded simplified geometry cache")
        return load_geo_table(cache)

    gdf = _from_database(cfg)
    if gdf is None:
        gdf = _from_parquet(cfg)
        log("dashboard: loaded data from Parquet")

    gdf = gdf.dropna(subset=["region_id"]).copy()

    # Detailed boundaries make the browser slow. 0.02 degrees (~2 km) keeps
    # the shapes recognisable and the page fast.
    gdf["geometry"] = gdf.geometry.simplify(0.02, preserve_topology=True)

    # A few helper columns used by the hover boxes and charts.
    gdf["country"] = gdf["country"].fillna(gdf["iso3"])

    # The database view exposes `rank_equal` as `risk_rank`, but the Parquet
    # fallback does not have that column at all. Derive it when missing so
    # both data paths behave the same way.
    if "risk_rank" not in gdf.columns:
        gdf["risk_rank"] = gdf["risk_equal"].rank(ascending=False, method="min")
    else:
        gdf["risk_rank"] = gdf["risk_rank"].fillna(
            gdf["risk_equal"].rank(ascending=False, method="min")
        )

    # Write the cache last, so a crash above never leaves a half-built file.
    gdf.to_parquet(cache, index=False)
    log(f"dashboard: cached simplified geometry -> {cache.name}")
    return gdf

