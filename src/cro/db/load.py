"""Load the analysis tables into PostGIS.

The dashboard and anyone exploring the data can then use SQL. If the
database is not running, the function says so clearly and the rest of the
project keeps working from the Parquet files (that is the "fallback").

Run it with:
    docker compose up -d
    cro load
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text

from cro.config import database_url, load_config
from cro.utils import log


def get_engine(cfg: dict):
    """Create a database engine, or return None if the server is unreachable."""
    url = database_url(cfg)
    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except Exception as error:
        log(f"database: not available ({str(error)[:120]})")
        return None


def recreate_schema(engine) -> None:
    """Drop and recreate the tables so a reload always starts clean."""
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")

    with engine.begin() as connection:
        # CASCADE removes the view and foreign keys in the right order.
        connection.execute(text("DROP VIEW IF EXISTS vw_region_profile CASCADE"))
        for table in ["fact_risk", "fact_development", "fact_exposure",
                      "fact_population", "fact_climate", "dim_region", "dim_country"]:
            connection.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
        connection.execute(text(schema))


def build_facts(master: pd.DataFrame, climate: pd.DataFrame,
                development: pd.DataFrame) -> dict:
    """Turn the wide analysis table into the long fact tables."""
    countries = master[["iso3", "country"]].drop_duplicates()

    # Climate facts: one row per region, indicator and weighting.
    indicator_columns = [c for c in climate.columns if c.endswith("_area")]
    rows = []
    for column in indicator_columns:
        indicator = column.replace("_area", "")
        for record in climate.itertuples():
            rows.append({
                "region_id": record.region_id,
                "indicator": indicator,
                "weighting": "area",
                "value": getattr(record, column),
                "n_points": record.n_points,
            })
    for column in [c for c in climate.columns if c.endswith("_pop")]:
        indicator = column.replace("_pop", "")
        for record in climate.itertuples():
            value = getattr(record, column)
            if pd.isna(value):
                continue
            rows.append({
                "region_id": record.region_id,
                "indicator": indicator,
                "weighting": "population",
                "value": value,
                "n_points": record.n_points,
            })
    climate_facts = pd.DataFrame(rows)

    population = master[[
        "region_id", "population", "area_km2", "pop_density",
    ]].copy()
    population["year"] = int(load_config()["population"]["year"])

    exposure = master[[
        "region_id", "person_days_heat", "pop_weighted_hd35",
        "share_pop_high_heat", "high_heat_threshold",
    ]].copy()

    # One row per region and per index version, so the database keeps the
    # main index ("v1_equal") and the two robustness versions.
    risk_parts = []
    for version in ["equal", "additive", "per_person"]:
        part = master[[
            "region_id", "hazard_equal", "exposure_score", "vulnerability",
            f"risk_{version}", f"rank_{version}",
        ]].rename(columns={
            "hazard_equal": "hazard",
            "exposure_score": "exposure",
            f"risk_{version}": "risk",
            f"rank_{version}": "risk_rank",
        })
        part["index_version"] = f"v1_{version}"
        risk_parts.append(part)
    risk = pd.concat(risk_parts, ignore_index=True)

    return {
        "dim_country": countries,
        "fact_climate": climate_facts,
        "fact_population": population,
        "fact_exposure": exposure,
        "fact_risk": risk,
        "fact_development": development[[
            "region_id", "indicator", "value", "year", "level", "source",
        ]].drop_duplicates(["region_id", "indicator"]),
    }


def run() -> bool:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])

    engine = get_engine(cfg)
    if engine is None:
        log("database: skipping load. The Parquet files in data/processed are still usable.")
        return False

    master = pd.read_parquet(processed / "region_master.parquet")
    climate = pd.read_parquet(processed / "climate_regions.parquet")
    development = pd.read_parquet(processed / "development_regions.parquet")
    regions = gpd.read_parquet(processed / "regions.parquet")

    recreate_schema(engine)
    facts = build_facts(master, climate, development)

    facts["dim_country"].to_sql("dim_country", engine, if_exists="append", index=False)

    # Regions carry geometry, so we use GeoPandas' PostGIS writer.
    regions_out = regions[[
        "region_id", "iso3", "region_name", "region_type", "area_km2",
        "centroid_lon", "centroid_lat", "is_remote", "geometry",
    ]].rename(columns={"geometry": "geom"})
    regions_out = gpd.GeoDataFrame(regions_out, geometry="geom", crs="EPSG:4326")
    regions_out.to_postgis("dim_region", engine, if_exists="append", index=False,
                           chunksize=100)

    for name in ["fact_climate", "fact_population", "fact_exposure",
                 "fact_development", "fact_risk"]:
        facts[name].to_sql(name, engine, if_exists="append", index=False,
                           chunksize=1000, method="multi")
        log(f"database: loaded {len(facts[name]):,} rows into {name}")

    # The convenience view is created by schema.sql inside `recreate_schema`,
    # so it is deliberately defined in exactly one place.
    log("database: load finished")
    return True


if __name__ == "__main__":
    run()
