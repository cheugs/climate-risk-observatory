-- ---------------------------------------------------------------------------
-- Database schema for the Climate Risk & Human Development Observatory.
--
-- The design is a small star schema:
--   dim_*  = descriptive tables (countries, regions)
--   fact_* = measurements (climate, population, development, risk)
--
-- Keeping the facts in "long" format (one row per region + indicator)
-- means we can add a new indicator without changing the table structure.
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- Dimensions
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_country (
    iso3        CHAR(3) PRIMARY KEY,
    country     TEXT NOT NULL,
    region      TEXT,          -- World Bank region, filled in by the loader
    income_group TEXT
);

CREATE TABLE IF NOT EXISTS dim_region (
    region_id    TEXT PRIMARY KEY,
    iso3         CHAR(3) REFERENCES dim_country(iso3),
    region_name  TEXT NOT NULL,
    region_type  TEXT,
    area_km2     DOUBLE PRECISION,
    centroid_lon DOUBLE PRECISION,
    centroid_lat DOUBLE PRECISION,
    is_remote    BOOLEAN DEFAULT FALSE,
    geom         GEOMETRY(MULTIPOLYGON, 4326)
);

-- A spatial index makes "which region is this point in?" fast.
CREATE INDEX IF NOT EXISTS idx_region_geom ON dim_region USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_region_iso3 ON dim_region (iso3);

-- ---------------------------------------------------------------------------
-- Climate
-- ---------------------------------------------------------------------------

-- Average hazard values for each region, with both weightings.
CREATE TABLE IF NOT EXISTS fact_climate (
    region_id  TEXT REFERENCES dim_region(region_id),
    indicator  TEXT NOT NULL,
    weighting  TEXT NOT NULL CHECK (weighting IN ('area', 'population')),
    value      DOUBLE PRECISION,
    n_points   INTEGER,
    PRIMARY KEY (region_id, indicator, weighting)
);

-- ---------------------------------------------------------------------------
-- Population and exposure
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_population (
    region_id    TEXT PRIMARY KEY REFERENCES dim_region(region_id),
    population   DOUBLE PRECISION,
    area_km2     DOUBLE PRECISION,
    pop_density  DOUBLE PRECISION,
    year         INTEGER
);

CREATE TABLE IF NOT EXISTS fact_exposure (
    region_id              TEXT PRIMARY KEY REFERENCES dim_region(region_id),
    person_days_heat       DOUBLE PRECISION,  -- population x heat days
    pop_weighted_hd35      DOUBLE PRECISION,
    share_pop_high_heat    DOUBLE PRECISION,
    high_heat_threshold    DOUBLE PRECISION
);

-- ---------------------------------------------------------------------------
-- Development
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_development (
    region_id  TEXT REFERENCES dim_region(region_id),
    indicator  TEXT NOT NULL,
    value      DOUBLE PRECISION,
    year       INTEGER,
    level      TEXT NOT NULL CHECK (level IN ('subnational', 'national')),
    source     TEXT,
    PRIMARY KEY (region_id, indicator)
);

-- ---------------------------------------------------------------------------
-- Composite risk
--
-- index_version keeps the three versions of the index: "v1_equal" (main),
-- "v1_additive" and "v1_per_person" (robustness checks).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fact_risk (
    region_id     TEXT REFERENCES dim_region(region_id),
    index_version TEXT NOT NULL,
    hazard        DOUBLE PRECISION,
    exposure      DOUBLE PRECISION,
    vulnerability DOUBLE PRECISION,
    risk          DOUBLE PRECISION,
    risk_rank     INTEGER,
    PRIMARY KEY (region_id, index_version)
);

-- ---------------------------------------------------------------------------
-- Convenience view used by the dashboard and the report
-- ---------------------------------------------------------------------------

-- Dropping first means the column list can change without PostgreSQL
-- complaining that an existing view cannot lose columns.
DROP VIEW IF EXISTS vw_region_profile CASCADE;

CREATE VIEW vw_region_profile AS
SELECT
    r.region_id,
    r.iso3,
    COALESCE(c.country, r.iso3) AS country,
    r.region_name,
    r.area_km2,
    r.centroid_lon,
    r.centroid_lat,
    p.population,
    p.pop_density,
    e.person_days_heat,
    e.pop_weighted_hd35,
    e.share_pop_high_heat,
    -- Two simple indicators joined in so the dashboard can draw its charts
    -- without a second round trip to the database.
    cl.value AS hd35_area,
    d.value  AS shdi,
    -- The names here match the Parquet files (`hazard_equal`, `risk_equal`),
    -- so the app does not need to know which store it is reading from.
    k.hazard       AS hazard_equal,
    k.exposure     AS exposure_score,
    k.vulnerability,
    k.risk         AS risk_equal,
    k.risk_rank
FROM dim_region r
LEFT JOIN dim_country c   ON c.iso3 = r.iso3
LEFT JOIN fact_population p ON p.region_id = r.region_id
LEFT JOIN fact_exposure e ON e.region_id = r.region_id
LEFT JOIN fact_climate cl ON cl.region_id = r.region_id
                         AND cl.indicator = 'hd35'
                         AND cl.weighting = 'area'
LEFT JOIN fact_development d ON d.region_id = r.region_id
                            AND d.indicator = 'shdi'
LEFT JOIN fact_risk k     ON k.region_id = r.region_id
                          AND k.index_version = 'v1_equal';
