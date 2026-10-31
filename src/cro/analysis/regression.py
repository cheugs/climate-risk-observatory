"""Linear regression for hypothesis H2.

H2 asks: is the link between climate hazard and development still there
when we compare regions *inside* the same country?

Why this matters: India is both hotter and less developed than France and
the USA. A simple correlation on all regions could just say "India is
different". Adding one dummy variable per country (a "country effect")
removes the average difference between countries, so the hazard
coefficient only uses differences between regions of the same country.

Two models:
    M1  shdi ~ hazard                     (all regions, no country effect)
    M2  shdi ~ hazard + country dummies   (comparison inside countries)

We also fit M1 separately for each country.

How to read the coefficient: hazard goes from 0 to 1, so the coefficient
is the change in SHDI between the least and the most hazardous region.
Divide it by 10 to get the change for +0.1 of hazard.

We use HC3 robust standard errors: they stay correct when the spread of
the errors is not the same for every region.

These models show associations. They do not prove that climate causes
low development.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

from cro.config import load_config
from cro.utils import log, save_table

MODELS = [
    ("M1 all regions", "shdi ~ hazard_equal"),
    ("M2 country effects", "shdi ~ hazard_equal + C(iso3)"),
]


def fit_model(data: pd.DataFrame, formula: str, name: str) -> dict:
    """Fit one OLS model and return the hazard coefficient as a table row."""
    model = smf.ols(formula, data=data).fit(cov_type="HC3")
    ci_low, ci_high = model.conf_int().loc["hazard_equal"]
    return {
        "model": name,
        "term": "hazard_equal",
        "beta": model.params["hazard_equal"],
        "std_error": model.bse["hazard_equal"],
        "p_value": model.pvalues["hazard_equal"],
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n_obs": int(model.nobs),
        "r_squared": model.rsquared,
    }


def country_slopes(data: pd.DataFrame, min_regions: int = 5) -> pd.DataFrame:
    """Fit M1 separately for each country.

    France has only 13 regions, so its result is uncertain. The confidence
    interval shows this clearly.
    """
    rows = []
    for iso3, group in data.groupby("iso3"):
        if len(group) < min_regions:
            continue
        row = fit_model(group, "shdi ~ hazard_equal", iso3)
        rows.append({
            "iso3": iso3,
            "n_regions": row["n_obs"],
            "slope": row["beta"],
            "std_error": row["std_error"],
            "p_value": row["p_value"],
            "ci_low": row["ci_low"],
            "ci_high": row["ci_high"],
            "r_squared": row["r_squared"],
        })
    return pd.DataFrame(rows)


def run() -> pd.DataFrame:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    tables = Path(cfg["paths"]["outputs"]) / "tables"

    master = pd.read_parquet(processed / "region_master.parquet")
    data = master.dropna(subset=["shdi", "hazard_equal"]).copy()

    coefficients = pd.DataFrame(
        [fit_model(data, formula, name) for name, formula in MODELS]
    ).round(4)
    save_table(coefficients, processed / "regression_coefficients.parquet")
    coefficients.to_csv(tables / "t07_regression_coefficients.csv", index=False)

    slopes = country_slopes(data, cfg["analysis"]["min_regions_per_country"]).round(4)
    save_table(slopes, processed / "country_slopes.parquet")
    slopes.to_csv(tables / "t08_country_slopes.csv", index=False)

    log("regression: " + ", ".join(name for name, _ in MODELS))
    return coefficients


if __name__ == "__main__":
    run()
