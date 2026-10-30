"""Regression models for hypothesis H3.

H3 asks: is the link between climate hazard and development still there
when we compare regions *inside* the same country?

Why that matters: India, France and the USA differ in history, income and
institutions. A simple correlation could just be picking up "poor countries
are hotter". Country fixed effects remove all differences *between*
countries and only use differences *within* a country.

We are careful about language: these models describe associations. They do
not prove that climate causes poverty.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from cro.config import load_config
from cro.utils import log, save_table


def prepare(master: pd.DataFrame) -> pd.DataFrame:
    """Create the variables used in the models."""
    data = master.dropna(subset=["shdi", "hazard_equal"]).copy()

    # Standardise the outcome and the main predictor. The coefficient then
    # reads as "a one standard deviation increase in hazard is associated
    # with this many standard deviations of SHDI".
    for column in ["shdi", "hazard_equal", "hazard_heat", "hazard_dry", "hazard_wet"]:
        data[f"{column}_z"] = (data[column] - data[column].mean()) / data[column].std(ddof=0)

    data["log_density_z"] = _z(np.log1p(data["pop_density"]))
    data["abs_lat_z"] = _z(data["centroid_lat"].abs())
    data["remote"] = data["is_remote"].astype(int)

    # A country id is needed for fixed effects.
    data["country"] = data["iso3"]
    return data


def _z(series: pd.Series) -> pd.Series:
    return (series - series.mean()) / series.std(ddof=0)


def fit_model(data: pd.DataFrame, formula: str, name: str,
              cluster: bool = False) -> dict:
    """Fit one OLS model and return a tidy row per coefficient."""
    model = smf.ols(formula, data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["country"]}
    ) if cluster else smf.ols(formula, data=data).fit(cov_type="HC3")

    rows = []
    for term in model.params.index:
        if term == "Intercept" or term.startswith("C(country)"):
            continue
        rows.append({
            "model": name,
            "term": term,
            "beta": model.params[term],
            "std_error": model.bse[term],
            "t_value": model.tvalues[term],
            "p_value": model.pvalues[term],
            "ci_low": model.conf_int().loc[term, 0],
            "ci_high": model.conf_int().loc[term, 1],
            "n_obs": int(model.nobs),
            "r_squared": model.rsquared,
            "covariance": "cluster (country)" if cluster else "HC3",
        })

    return {"rows": rows, "model": model}


def country_slopes(data: pd.DataFrame) -> pd.DataFrame:
    """Fit the hazard-development line separately for each country.

    The slope tells us whether the within-country pattern matches the
    cross-country one. France has only 13 regions, so its estimate is noisy
    and this table shows that honestly.
    """
    rows = []
    for iso3, group in data.groupby("iso3"):
        if len(group) < 5:
            continue
        model = smf.ols("shdi_z ~ hazard_equal_z", data=group).fit(cov_type="HC3")
        rows.append({
            "iso3": iso3,
            "n_regions": len(group),
            "slope": model.params["hazard_equal_z"],
            "std_error": model.bse["hazard_equal_z"],
            "p_value": model.pvalues["hazard_equal_z"],
            "ci_low": model.conf_int().loc["hazard_equal_z", 0],
            "ci_high": model.conf_int().loc["hazard_equal_z", 1],
            "r_squared": model.rsquared,
        })
    return pd.DataFrame(rows)


def run() -> pd.DataFrame:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    tables = Path(cfg["paths"]["outputs"]) / "tables"

    master = pd.read_parquet(processed / "region_master.parquet")
    data = prepare(master)

    # With only three countries, cluster-robust errors are not reliable.
    # The global run has many more countries, so we switch automatically.
    n_countries = data["iso3"].nunique()
    use_cluster = n_countries >= 20

    models = [
        ("M1 pooled", "shdi_z ~ hazard_equal_z", False),
        ("M2 controls", "shdi_z ~ hazard_equal_z + log_density_z + abs_lat_z + remote", False),
        ("M3 country FE", "shdi_z ~ hazard_equal_z + log_density_z + abs_lat_z + remote + C(country)", use_cluster),
        ("M4 components", "shdi_z ~ hazard_heat_z + hazard_dry_z + hazard_wet_z + log_density_z + abs_lat_z + remote + C(country)", use_cluster),
    ]

    rows = []
    fitted = {}
    for name, formula, cluster in models:
        result = fit_model(data, formula, name, cluster=cluster)
        rows.append(pd.DataFrame(result["rows"]))
        fitted[name] = result["model"]

    coefficients = pd.concat(rows, ignore_index=True).round(4)
    save_table(coefficients, processed / "regression_coefficients.parquet")
    coefficients.to_csv(tables / "t07_regression_coefficients.csv", index=False)

    # Model fit summary.
    fit_rows = []
    for name, model in fitted.items():
        fit_rows.append({
            "model": name,
            "n_obs": int(model.nobs),
            "r_squared": model.rsquared,
            "adj_r_squared": model.rsquared_adj,
            "aic": model.aic,
        })
    fit_summary = pd.DataFrame(fit_rows).round(4)
    save_table(fit_summary, processed / "regression_fit.parquet")

    # Within-country slopes for the forest plot.
    slopes = country_slopes(data).round(4)
    save_table(slopes, processed / "country_slopes.parquet")
    slopes.to_csv(tables / "t08_country_slopes.csv", index=False)

    log("regression: " + ", ".join(fitted))
    return coefficients


if __name__ == "__main__":
    run()
