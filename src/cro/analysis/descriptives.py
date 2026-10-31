"""Descriptive statistics: what the data looks like before any testing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cro.config import load_config
from cro.utils import log, save_table


def summary_by_country(master: pd.DataFrame) -> pd.DataFrame:
    """One row per country plus an "ALL" row."""
    columns = {
        "n_regions": ("region_id", "count"),
        "population_m": ("population", lambda x: x.sum() / 1e6),
        "hazard_mean": ("hazard_equal", "mean"),
        "exposure_mean": ("exposure_score", "mean"),
        "vulnerability_mean": ("vulnerability", "mean"),
        "risk_median": ("risk_equal", "median"),
        "person_days_heat_bn": ("person_days_heat", lambda x: x.sum() / 1e9),
    }

    rows = []
    for name, group in [("ALL", master)] + list(master.groupby("iso3")):
        row = {"group": name}
        for label, (column, func) in columns.items():
            # .agg accepts either a function (mean) or a string ("count").
            row[label] = group[column].agg(func)
        rows.append(row)

    return pd.DataFrame(rows).round(3)


def indicator_summary(master: pd.DataFrame) -> pd.DataFrame:
    """Mean, median and range of each climate indicator per country."""
    indicators = ["hd35_area", "tr25_area", "cdd_area", "wbal_area", "rx1d_area", "r50_area"]
    rows = []
    for iso3, group in master.groupby("iso3"):
        for indicator in indicators:
            rows.append({
                "iso3": iso3,
                "indicator": indicator.replace("_area", ""),
                "mean": group[indicator].mean(),
                "median": group[indicator].median(),
                "min": group[indicator].min(),
                "max": group[indicator].max(),
            })
    return pd.DataFrame(rows).round(2)


def top_regions(master: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """The highest and lowest risk regions, in one table."""
    columns = ["region_name", "country", "iso3", "population", "hazard_equal",
               "exposure_score", "vulnerability", "risk_equal", "rank_equal",
               "rank_in_country"]
    top = master.nlargest(n, "risk_equal")[columns].assign(group="highest_risk")
    bottom = master.nsmallest(n, "risk_equal")[columns].assign(group="lowest_risk")
    return pd.concat([top, bottom], ignore_index=True).round(4)


def run() -> dict:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    tables = Path(cfg["paths"]["outputs"]) / "tables"
    tables.mkdir(parents=True, exist_ok=True)

    master = pd.read_parquet(processed / "region_master.parquet")

    summary = summary_by_country(master)
    save_table(summary, processed / "desc_summary.parquet")
    summary.to_csv(tables / "t01_summary_by_country.csv", index=False)

    indicators = indicator_summary(master)
    save_table(indicators, processed / "desc_indicators.parquet")
    indicators.to_csv(tables / "t02_climate_by_country.csv", index=False)

    extremes = top_regions(master)
    save_table(extremes, processed / "desc_top_regions.parquet")
    extremes.to_csv(tables / "t03_top_bottom_regions.csv", index=False)

    log(f"descriptives: wrote 3 tables to {tables}")
    return {"summary": summary, "indicators": indicators, "top": extremes}


if __name__ == "__main__":
    run()
