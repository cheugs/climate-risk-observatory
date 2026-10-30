"""Build the analysis table.

This step turns the raw measurements into three interpretable blocks:

    Hazard        = how extreme the climate is (heat, dry, wet)
    Exposure      = how many people live in those conditions
    Vulnerability = how little development there is to cope with them

Then it combines them into a Risk score following the IPCC idea:

    Risk = Hazard x Exposure x Vulnerability

Every block is turned into a 0-1 score using percentile ranks, so the
units (days, mm, index points) do not need to be comparable.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cro.config import load_config
from cro.utils import log, percentile_rank, save_table


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

    Wet and dry are kept apart on purpose. A desert and a monsoon coast can
    both be "high hazard", but for opposite reasons, so averaging all six
    indicators into one number would hide that.
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

    # A second version that lets the data decide the weights (PCA).
    data["hazard_pca"] = _pca_hazard(p[["hd35", "tr25", "cdd", "wbal", "rx1d", "r50"]])

    # A third version using population-weighted climate instead of area-weighted.
    pop_cols = ["hd35_pop", "tr25_pop", "cdd_pop", "wbal_pop", "rx1d_pop", "r50_pop"]
    if all(col in data.columns for col in pop_cols):
        pp = pd.DataFrame(index=data.index)
        pp["hd35"] = percentile_rank(data["hd35_pop"])
        pp["tr25"] = percentile_rank(data["tr25_pop"])
        pp["cdd"] = percentile_rank(data["cdd_pop"])
        pp["wbal"] = percentile_rank(-data["wbal_pop"])
        pp["rx1d"] = percentile_rank(data["rx1d_pop"])
        pp["r50"] = percentile_rank(data["r50_pop"])
        data["hazard_popclimate"] = pp.mean(axis=1)

    return data


def _pca_hazard(indicators: pd.DataFrame) -> pd.Series:
    """First principal component of the hazard indicators.

    PCA finds the single direction that explains the most variation. We use
    it as a data-driven alternative to equal weights. The sign is fixed so
    that higher values always mean "more hazard".
    """
    x = indicators.dropna()
    if len(x) < 10:
        return pd.Series(np.nan, index=indicators.index)

    # Standardise because the indicators have different variances.
    z = (x - x.mean()) / x.std(ddof=0)
    # SVD is a stable way to get principal components without extra packages.
    u, s, vt = np.linalg.svd(z.to_numpy(), full_matrices=False)
    component = u[:, 0] * s[0]

    # Flip the component if it points the "wrong" way.
    if np.corrcoef(component, z.mean(axis=1).to_numpy())[0, 1] < 0:
        component = -component

    scores = pd.Series(component, index=x.index)
    return percentile_rank(scores).reindex(indicators.index)


# ---------------------------------------------------------------------------
# 2. Exposure: where people actually live
# ---------------------------------------------------------------------------

def build_exposure(point_year: pd.DataFrame, point_pop: pd.DataFrame,
                   points: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Build exposure measures from point-level population and climate.

    person_days_heat is the headline exposure measure: if a point has
    100,000 people and 40 heat days per year, it contributes 4,000,000
    person-days of extreme heat.
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

    # Exposure as a 0-1 score. We use the log of person-days because a few
    # very large regions (Uttar Pradesh, California) would otherwise dominate.
    master["exposure_score"] = percentile_rank(np.log1p(master["person_days_heat"]))

    # The three risk versions.
    master["risk_equal"] = (
        master["hazard_equal"] * master["exposure_score"] * master["vulnerability"]
    )
    master["risk_additive"] = master[
        ["hazard_equal", "exposure_score", "vulnerability"]
    ].mean(axis=1)
    master["risk_pca"] = (
        master["hazard_pca"] * master["exposure_score"] * master["vulnerability"]
    )
    if "hazard_popclimate" in master.columns:
        master["risk_popclimate"] = (
            master["hazard_popclimate"] * master["exposure_score"] * master["vulnerability"]
        )

    # Ranks (1 = highest risk).
    for column in ["risk_equal", "risk_additive", "risk_pca", "risk_popclimate"]:
        if column in master.columns:
            master[column.replace("risk", "rank")] = master[column].rank(
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
    for version in ["equal", "additive", "pca", "popclimate"]:
        column = f"risk_{version}"
        if column not in master.columns:
            continue
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
