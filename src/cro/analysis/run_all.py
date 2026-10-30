"""Run the whole analysis in the right order and write a short summary.

The summary file is useful for two reasons:
1. it is a quick check that every step produced sensible numbers, and
2. it gives the report a first draft of the findings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from cro.config import load_config
from cro.utils import log
from cro.analysis import descriptives, regression, spatial, tests


def run() -> dict:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    outputs = Path(cfg["paths"]["outputs"])

    log("analysis: descriptives")
    desc = descriptives.run()

    log("analysis: hypothesis tests")
    tested = tests.run()

    log("analysis: regression")
    coefficients = regression.run()

    log("analysis: spatial")
    moran = spatial.run()

    master = pd.read_parquet(processed / "region_master.parquet")
    h1 = tested["tests"].iloc[0]
    h2 = tested["tests"].iloc[1]

    key = {
        "n_regions": int(len(master)),
        "n_countries": int(master["iso3"].nunique()),
        "population_millions": round(master["population"].sum() / 1e6, 1),
        "regions_with_development": int(master["shdi"].notna().sum()),
        "h1_concentration_ratio": round(float(h1["concentration_ratio"]), 2),
        "h1_ci": [round(float(h1["ci_low"]), 2), round(float(h1["ci_high"]), 2)],
        "h2_median_shdi_high_hazard": round(float(h2["median_shdi_high_hazard"]), 3),
        "h2_median_shdi_low_hazard": round(float(h2["median_shdi_low_hazard"]), 3),
        "h2_p_value": float(f"{h2['p_value']:.3g}"),
        "h2_cliffs_delta": round(float(h2["cliffs_delta"]), 3),
        "h3_country_fe_beta": _country_fe_beta(coefficients),
        "moran_i": {
            f"{row['scope']}:{row['variable']}": round(float(row["morans_i"]), 3)
            for _, row in moran[moran["scope"] != "all countries"].iterrows()
            if pd.notna(row["morans_i"])
        },
    }

    with open(processed / "key_numbers.json", "w", encoding="utf-8") as f:
        json.dump(key, f, indent=2)

    _write_summary(key, master, outputs)
    log("analysis: finished")
    return key


def _country_fe_beta(coefficients: pd.DataFrame) -> dict | None:
    """Pull the hazard coefficient from the country fixed-effects model."""
    row = coefficients[
        (coefficients["model"] == "M3 country FE")
        & (coefficients["term"] == "hazard_equal_z")
    ]
    if row.empty:
        return None
    row = row.iloc[0]
    return {
        "beta": round(float(row["beta"]), 3),
        "ci": [round(float(row["ci_low"]), 3), round(float(row["ci_high"]), 3)],
        "p_value": float(f"{row['p_value']:.3g}"),
        "n": int(row["n_obs"]),
    }


def _write_summary(key: dict, master: pd.DataFrame, outputs: Path) -> None:
    """Write a plain-language summary of the results."""
    top = master.nlargest(10, "risk_equal")[
        ["region_name", "country", "risk_equal"]
    ]

    lines = [
        "# Key results",
        "",
        f"- Regions analysed: **{key['n_regions']}** in **{key['n_countries']}** countries.",
        f"- Population covered: **{key['population_millions']:.1f} million**.",
        f"- Regions with development data: **{key['regions_with_development']}**.",
        "",
        "## H1 - exposure is concentrated",
        f"- The top 10% most hazardous regions hold **{key['h1_concentration_ratio']:.2f}x** "
        f"their population share of person-days of extreme heat "
        f"(95% CI {key['h1_ci'][0]:.2f} to {key['h1_ci'][1]:.2f}).",
        "",
        "## H2 - high hazard goes with lower development",
        f"- Median SHDI in high-hazard regions: **{key['h2_median_shdi_high_hazard']:.3f}**.",
        f"- Median SHDI in low-hazard regions: **{key['h2_median_shdi_low_hazard']:.3f}**.",
        f"- Mann-Whitney p = **{key['h2_p_value']:.3g}**, Cliff's delta = **{key['h2_cliffs_delta']:.2f}**.",
        "",
        "## H3 - does it survive country fixed effects?",
    ]

    if key["h3_country_fe_beta"]:
        beta = key["h3_country_fe_beta"]
        lines.append(
            f"- A one standard deviation increase in hazard is associated with "
            f"**{beta['beta']:.2f}** standard deviations of SHDI "
            f"(95% CI {beta['ci'][0]:.2f} to {beta['ci'][1]:.2f}, p = {beta['p_value']:.3g}, "
            f"N = {beta['n']}) within countries."
        )
    else:
        lines.append("- Model could not be estimated.")

    lines += [
        "",
        "## H4 - spatial clustering",
    ]
    for variable, value in key["moran_i"].items():
        lines.append(f"- Moran's I for `{variable}`: **{value:.2f}**.")

    lines += ["", "## Highest-risk regions", ""]
    for _, row in top.iterrows():
        lines.append(f"1. {row['region_name']} ({row['country']}) - risk {row['risk_equal']:.3f}")

    lines += [
        "",
        "> These are associations, not causal effects. See the limitations section.",
    ]

    path = outputs / "report" / "key_results.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run()
