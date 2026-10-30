"""Spatial analysis: are hazard and low development clustered on the map?

A normal correlation treats every region as independent. Neighbouring
regions are not independent: a drought in Rajasthan usually continues into
Gujarat. Moran's I measures whether similar values sit next to each other.

- Global Moran's I: one number for the whole study area.
- Local Moran's I (LISA): a cluster label for every region, which is what
  the "hotspot" map shows.

We use k-nearest-neighbour weights (k=5) instead of contiguity because
islands such as Lakshadweep have no land neighbours.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from esda.moran import Moran, Moran_Local
from libpysal.weights import Queen

from cro.config import load_config
from cro.utils import log, save_table

# esda's quadrant codes.
QUADRANT_LABELS = {1: "HH", 2: "LH", 3: "LL", 4: "HL"}
QUADRANT_MEANING = {
    "HH": "high value next to high values (hotspot)",
    "LL": "low value next to low values (cold spot)",
    "HL": "high value surrounded by low values (outlier)",
    "LH": "low value surrounded by high values (outlier)",
}


def _drop_islands(gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, list]:
    """Remove regions that have no land neighbours.

    Queen contiguity gives islands (Hawaii, Corsica, Lakshadweep, US
    territories) an empty neighbour list, which makes their row of the
    weights matrix all zeros. We remove them from the statistic and add
    them back afterwards with a clear "no neighbours" label.

    Note: the three pilot countries do not share a border, so the weights
    matrix has three separate blocks. Moran's I is still well defined, but
    it effectively measures clustering *within* each country. The report
    says this explicitly.
    """
    data = gdf.reset_index(drop=True)
    weights = Queen.from_dataframe(data, use_index=True, silence_warnings=True)
    island_positions = list(weights.islands)
    island_ids = data.iloc[island_positions]["region_id"].tolist() if island_positions else []

    if island_positions:
        data = data.drop(index=island_positions).reset_index(drop=True)

    return data, island_ids


def build_weights(gdf: gpd.GeoDataFrame):
    """Queen contiguity weights, row-standardised."""
    weights = Queen.from_dataframe(gdf, use_index=True, silence_warnings=True)
    weights.transform = "r"
    return weights


def global_moran(gdf: gpd.GeoDataFrame, column: str, permutations: int = 999,
                 seed: int = 42) -> dict:
    """Global Moran's I for one variable."""
    data = gdf.dropna(subset=[column]).reset_index(drop=True)
    data, dropped = _drop_islands(data)
    if len(data) < 5:
        return {"variable": column, "n_regions": 0, "morans_i": np.nan,
                "expected_i": np.nan, "z_score": np.nan, "p_value": np.nan,
                "p_sim": np.nan, "dropped_islands": len(dropped)}

    weights = build_weights(data)
    np.random.seed(seed)
    moran = Moran(data[column].to_numpy(), weights, permutations=permutations)

    return {
        "variable": column,
        "n_regions": len(data),
        "morans_i": moran.I,
        "expected_i": moran.EI,
        "z_score": moran.z_norm,
        "p_value": moran.p_norm,
        "p_sim": moran.p_sim,
        "dropped_islands": len(dropped),
    }


def local_moran(gdf: gpd.GeoDataFrame, column: str, permutations: int = 999,
                seed: int = 42) -> gpd.GeoDataFrame:
    """Local Moran's I with a cluster label for each region."""
    data = gdf.dropna(subset=[column]).reset_index(drop=True)
    connected, dropped = _drop_islands(data)

    np.random.seed(seed)
    weights = build_weights(connected)
    local = Moran_Local(connected[column].to_numpy(), weights, permutations=permutations)

    out = connected.copy()
    out["local_i"] = local.Is
    out["p_sim"] = local.p_sim
    out["quadrant"] = [QUADRANT_LABELS[q] for q in local.q]
    out["cluster"] = np.where(out["p_sim"] <= 0.05, out["quadrant"], "not significant")

    # Add the island regions back with a clear "no neighbours" label.
    islands = data[data["region_id"].isin(dropped)].copy()
    if len(islands):
        islands["local_i"] = np.nan
        islands["p_sim"] = np.nan
        islands["quadrant"] = "none"
        islands["cluster"] = "no neighbours"

    return pd.concat([out, islands], ignore_index=True)


def run() -> pd.DataFrame:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    tables = Path(cfg["paths"]["outputs"]) / "tables"

    master = pd.read_parquet(processed / "region_master.parquet")
    regions = gpd.read_parquet(processed / "regions.parquet")

    gdf = regions[["region_id", "geometry"]].merge(master, on="region_id", how="inner")
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")

    variables = ["hazard_equal", "shdi", "exposure_score", "risk_equal"]

    # 1. Overall statistic. Read it with care: the pilot countries do not
    #    share a border, so this mostly reflects within-country similarity.
    results = []
    for column in variables:
        if column in gdf.columns:
            row = global_moran(gdf, column)
            row["scope"] = "all countries"
            results.append(row)

    # 2. One statistic per country. This is the version the report relies on,
    #    because the neighbour graph is complete inside each country.
    for iso3, group in gdf.groupby("iso3"):
        for column in variables:
            if column not in group.columns or group[column].notna().sum() < 5:
                continue
            row = global_moran(group, column)
            row["scope"] = iso3
            results.append(row)

    moran_table = pd.DataFrame(results).round(4)
    save_table(moran_table, processed / "moran_global.parquet")
    moran_table.to_csv(tables / "t09_morans_i.csv", index=False)

    # 3. Local clusters, computed inside each country.
    lisa_parts = []
    for iso3, group in gdf.groupby("iso3"):
        for column in ["risk_equal", "shdi"]:
            if column not in group.columns or group[column].notna().sum() < 5:
                continue
            lisa = local_moran(group, column)
            lisa = lisa[["region_id", "region_name", "iso3", "local_i", "p_sim",
                         "quadrant", "cluster", column, "geometry"]].copy()
            lisa["variable"] = column
            lisa_parts.append(lisa)

    lisa_all = gpd.GeoDataFrame(pd.concat(lisa_parts, ignore_index=True),
                                geometry="geometry", crs="EPSG:4326")
    save_table(lisa_all, processed / "lisa_clusters.parquet")

    within = moran_table[moran_table["scope"] != "all countries"]
    summary = ", ".join(
        f"{r['scope']}-{r['variable']}={r['morans_i']:.2f}"
        for _, r in within.iterrows() if pd.notna(r["morans_i"])
    )
    log(f"spatial: {summary}")
    return moran_table


if __name__ == "__main__":
    run()
