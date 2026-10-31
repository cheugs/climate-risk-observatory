"""Build the analysis table.

This step turns the raw data into three simple scores, each between 0 and 1:

    Hazard        = how extreme the climate is (heat, dry, wet)
    Exposure      = how many people live in the region
    Vulnerability = how low human development is

Then it combines them into one Risk score, following the IPCC idea that
risk needs all three parts:

    Risk = Hazard x Exposure x Vulnerability

We use percentile ranks to build each score, so we can mix days,
millimetres and index points without unit problems.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cro.config import load_config
from cro.utils import log, percentile_rank, save_table

# The three versions of the risk index. "equal" is the main one.
VERSIONS = ["equal", "additive", "per_person"]


# ---------------------------------------------------------------------------
# Load the pieces created by the ingest step
# ---------------------------------------------------------------------------

def load_inputs() -> dict:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])

    return {
        "regions": pd.read_parquet(processed / "regions.parquet"),
        "population": pd.read_parquet(processed / "population_regions.parquet"),
        "climate": pd.read_parquet(processed / "climate_regions.parquet"),
        "point_year": pd.read_parquet(processed / "climate_point_year.parquet"),
        "points": pd.read_parquet(processed / "climate_points.parquet"),
        "point_pop": pd.read_parquet(processed / "point_population.parquet"),
        "development": pd.read_parquet(processed / "development_regions.parquet"),
    }


# ---------------------------------------------------------------------------
# 1. Hazard: heat, dry and wet sub-indices
# ---------------------------------------------------------------------------

def build_hazard(climate: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Turn the six climate indicators into a hazard score.

    We first build three sub-scores (heat, dry, wet), then take their mean.
    Wet and dry are kept apart because a desert and a monsoon coast can both
    be "high hazard", but for opposite reasons.
    """
    data = climate.copy()

    # Percentile ranks put every indicator on the same 0-1 scale.
    # For water balance, a *lower* value is worse, so we flip the sign.
    p = pd.DataFrame(index=data.index)
    p["hd35"] = percentile_rank(data["hd35_area"])
    p["tr25"] = percentile_rank(data["tr25_area"])
    p["cdd"] = percentile_rank(data["cdd_area"])
    p["wbal"] = percentile_rank(-data["wbal_area"])
    p["rx1d"] = percentile_rank(data["rx1d_area"])
    p["r50"] = percentile_rank(data["r50_area"])

    data["hazard_heat"] = p[["hd35", "tr25"]].mean(axis=1)
    data["hazard_dry"] = p[["cdd", "wbal"]].mean(axis=1)
    data["hazard_wet"] = p[["rx1d", "r50"]].mean(axis=1)
    data["hazard_equal"] = data[["hazard_heat", "hazard_dry", "hazard_wet"]].mean(axis=1)

    return data


# ---------------------------------------------------------------------------
# 2. Exposure: where people actually live
# ---------------------------------------------------------------------------

def build_exposure(point_year: pd.DataFrame, point_pop: pd.DataFrame,
                   points: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Extra heat measures that use population and climate together.

    These columns are descriptive only: they are shown in the maps and the
    dashboard, but they are NOT used in the risk index. (The index already
    counts heat in the hazard score; using heat again in the exposure score
    would count it twice.)

    Example: a point with 100,000 people and 40 heat days per year gives
    4,000,000 person-days of extreme heat.
    """
    # Average heat days over the baseline period for every sample point.
    baseline = point_year[
        (point_year["year"] >= cfg["climate"]["baseline_start"])
        & (point_year["year"] <= cfg["climate"]["baseline_end"])
    ].groupby("point_id")["hd35"].mean().reset_index()
    baseline = baseline.rename(columns={"hd35": "hd35_baseline"})

    data = point_pop.merge(baseline, on="point_id", how="inner")
    data = data.merge(points[["point_id", "region_id"]].drop_duplicates(), on="point_id")

    # "High heat" is defined relative to this study area: the top 20% of
    # sample points. The threshold is saved so the report can state it.
    threshold = float(data["hd35_baseline"].quantile(0.80))
    data["high_heat"] = data["hd35_baseline"] >= threshold

    rows = []
    for region_id, group in data.groupby("region_id"):
        population = group["point_pop"].sum()
        person_days = float((group["point_pop"] * group["hd35_baseline"]).sum())

        rows.append({
            "region_id": region_id,
            "person_days_heat": person_days,
            "pop_weighted_hd35": person_days / population if population > 0 else np.nan,
            "share_pop_high_heat": (
                group.loc[group["high_heat"], "point_pop"].sum() / population
                if population > 0 else np.nan
            ),
            "high_heat_threshold": threshold,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Vulnerability: the development side
# ---------------------------------------------------------------------------

def build_vulnerability(development: pd.DataFrame) -> pd.DataFrame:
    """Turn SHDI into a vulnerability score.

    Vulnerability is the opposite of development: regions with a low SHDI
    have less capacity to prepare for, cope with and recover from climate
    stress.

    We deliberately do NOT fill missing SHDI values with the country mean.
    That would invent within-country variation that does not exist. Those
    regions stay in the hazard maps but are left out of the development
    models, and the report says how many that is.
    """
    shdi = development[development["indicator"] == "shdi"][
        ["region_id", "value", "year", "source", "match_score"]
    ].rename(columns={"value": "shdi", "year": "shdi_year"})

    shdi["development_score"] = percentile_rank(shdi["shdi"])
    shdi["vulnerability"] = 1 - shdi["development_score"]
    return shdi


# ---------------------------------------------------------------------------
# 4. Combine and save
# ---------------------------------------------------------------------------

def combine(inputs: dict, cfg: dict) -> pd.DataFrame:
    regions = inputs["regions"][[
        "region_id", "iso3", "country", "region_name", "region_type",
        "area_km2", "centroid_lon", "centroid_lat", "is_remote",
    ]].copy()

    hazard = build_hazard(inputs["climate"], cfg)
    exposure = build_exposure(inputs["point_year"], inputs["point_pop"],
                              inputs["points"], cfg)
    vulnerability = build_vulnerability(inputs["development"])

    master = (
        regions
        .merge(inputs["population"][["region_id", "population", "pop_density"]], on="region_id", how="left")
        .merge(hazard, on="region_id", how="left")
        .merge(exposure, on="region_id", how="left")
        .merge(vulnerability, on="region_id", how="left")
    )

    # Exposure = how many people live in the region, as a 0-1 score.
    # We use population only (not population x heat days) because heat is
    # already inside the hazard score.
    master["exposure_score"] = percentile_rank(master["population"])

    # Main risk index (product, IPCC idea).
    master["risk_equal"] = (
        master["hazard_equal"] * master["exposure_score"] * master["vulnerability"]
    )

    # Two other versions, used only to check that the ranking is stable:
    # - additive: the simple mean of the three scores;
    # - per_person: hazard x vulnerability, without population. Big regions
    #   always have a high exposure score, so this version shows which
    #   regions are risky for each person living there, whatever their size.
    master["risk_additive"] = master[
        ["hazard_equal", "exposure_score", "vulnerability"]
    ].mean(axis=1)
    master["risk_per_person"] = master["hazard_equal"] * master["vulnerability"]

    # Ranks (1 = highest risk).
    for version in VERSIONS:
        master[f"rank_{version}"] = master[f"risk_{version}"].rank(
            ascending=False, method="min"
        )

    # Rank inside the country. The scores are computed on all regions
    # together, so most Indian states rank above all US states. This rank
    # shows which regions stand out inside their own country.
    master["rank_in_country"] = master.groupby("iso3")["risk_equal"].rank(
        ascending=False, method="min"
    )

    # Flags that the analysis and the report can use.
    master["has_development"] = master["shdi"].notna()
    master["small_population"] = master["population"] < cfg["population"]["min_population"]

    return master


def run() -> pd.DataFrame:
    cfg = load_config()
    inputs = load_inputs()

    master = combine(inputs, cfg)

    processed = Path(cfg["paths"]["processed"])
    save_table(master, processed / "region_master.parquet")

    # A long table of the risk versions makes the robustness analysis simple.
    versions = []
    for version in VERSIONS:
        column = f"risk_{version}"
        part = master[["region_id", "iso3", "region_name", column]].copy()
        part["version"] = version
        part = part.rename(columns={column: "risk"})
        part["rank"] = part["risk"].rank(ascending=False, method="min")
        versions.append(part)
    save_table(pd.concat(versions, ignore_index=True), processed / "risk_versions.parquet")

    log(f"build: {len(master)} regions, "
        f"{master['has_development'].sum()} with development data")
    log(f"build: top 5 by risk_equal")
    top = master.nlargest(5, "risk_equal")[["region_name", "iso3", "risk_equal"]]
    print(top.to_string(index=False))

    return master


if __name__ == "__main__":
    run()
