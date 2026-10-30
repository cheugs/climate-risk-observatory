"""Descriptive statistics: what the data looks like before any testing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
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
               "exposure_score", "vulnerability", "risk_equal", "rank_equal"]
    top = master.nlargest(n, "risk_equal")[columns].assign(group="highest_risk")
    bottom = master.nsmallest(n, "risk_equal")[columns].assign(group="lowest_risk")
    return pd.concat([top, bottom], ignore_index=True).round(4)


def exposure_concentration(master: pd.DataFrame) -> pd.DataFrame:
    """Lorenz-style table: exposure versus population, sorted by hazard.

    This is the raw material for hypothesis H1. If climate exposure were
    spread evenly, the top 10% most hazardous regions would hold about 10%
    of the world's population and of the person-days of heat.
    """
    data = master.dropna(subset=["hazard_equal", "person_days_heat", "population"]).copy()
    data = data.sort_values("hazard_equal", ascending=False).reset_index(drop=True)

    total_pop = data["population"].sum()
    total_person_days = data["person_days_heat"].sum()

    data["cum_pop_share"] = data["population"].cumsum() / total_pop
    data["cum_person_days_share"] = data["person_days_heat"].cumsum() / total_person_days
    data["rank_hazard"] = np.arange(1, len(data) + 1)
    data["population_share"] = data["population"] / total_pop

    return data[[
        "rank_hazard", "region_name", "iso3", "hazard_equal", "population",
        "population_share", "person_days_heat", "cum_pop_share", "cum_person_days_share",
    ]]


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

    lorenz = exposure_concentration(master)
    save_table(lorenz, processed / "desc_lorenz.parquet")
    lorenz.to_csv(tables / "t04_exposure_concentration.csv", index=False)

    log(f"descriptives: wrote 4 tables to {tables}")
    return {"summary": summary, "indicators": indicators,
            "top": extremes, "lorenz": lorenz}


if __name__ == "__main__":
    run()
