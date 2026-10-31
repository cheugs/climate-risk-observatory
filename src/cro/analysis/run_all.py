"""Run the whole analysis in the right order and write a short summary.

The summary file (key_numbers.json) is read by the report and the
dashboard, so the numbers are never typed by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from cro.config import load_config
from cro.utils import log
from cro.analysis import descriptives, regression, tests


def run() -> dict:
    """Run every analysis step, then save key_numbers.json and key_results.md."""
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    outputs = Path(cfg["paths"]["outputs"])

    log("analysis: descriptives")
    descriptives.run()

    log("analysis: hypothesis tests (H1, H3)")
    tested = tests.run()

    log("analysis: regression (H2)")
    coefficients = regression.run()

    master = pd.read_parquet(processed / "region_master.parquet")
    h1 = tested["h1"].set_index("group")
    stability = tested["stability"]
    slopes = pd.read_parquet(processed / "country_slopes.parquet").set_index("iso3")

    def model(name: str) -> dict:
        row = coefficients[coefficients["model"] == name].iloc[0]
        return {
            "beta": round(float(row["beta"]), 3),
            "ci": [round(float(row["ci_low"]), 3), round(float(row["ci_high"]), 3)],
            "p_value": float(f"{row['p_value']:.3g}"),
            "n": int(row["n_obs"]),
        }

    key = {
        "n_regions": int(len(master)),
        "n_countries": int(master["iso3"].nunique()),
        "population_millions": round(master["population"].sum() / 1e6, 1),
        "regions_with_development": int(master["shdi"].notna().sum()),
        "h1": {
            group: {
                "rho": round(float(row["spearman_rho"]), 2),
                "p_value": float(f"{row['p_value']:.3g}"),
                "n": int(row["n_regions"]),
                "median_shdi_high_hazard": round(float(row["median_shdi_high_hazard"]), 3),
                "median_shdi_low_hazard": round(float(row["median_shdi_low_hazard"]), 3),
            }
            for group, row in h1.iterrows()
        },
        "h2_all_regions": model("M1 all regions"),
        "h2_country_effects": model("M2 country effects"),
        "h2_country_slopes": {
            iso3: round(float(row["slope"]), 3) for iso3, row in slopes.iterrows()
        },
        "h3_min_rho": round(float(stability["spearman_rho"].min()), 2),
        "h3_min_same_in_top10": int(stability["same_in_top10"].min()),
    }

    with open(processed / "key_numbers.json", "w", encoding="utf-8") as f:
        json.dump(key, f, indent=2)

    _write_summary(key, master, outputs)
    log("analysis: finished")
    return key


def _write_summary(key: dict, master: pd.DataFrame, outputs: Path) -> None:
    """Write the main results as a short Markdown file."""
    h1 = key["h1"]["ALL"]
    m1, m2 = key["h2_all_regions"], key["h2_country_effects"]
    lines = [
        "# Key results",
        "",
        f"- Regions analysed: **{key['n_regions']}** in **{key['n_countries']}** countries.",
        f"- Population covered: **{key['population_millions']:.1f} million**.",
        f"- Regions with development data: **{key['regions_with_development']}**.",
        "",
        "## H1 - more hazard goes with lower development",
        f"- All regions: Spearman rho = **{h1['rho']:.2f}** (p = {h1['p_value']:.2g}, "
        f"N = {h1['n']}).",
        f"- Median SHDI: **{h1['median_shdi_high_hazard']:.3f}** in the more hazardous half, "
        f"**{h1['median_shdi_low_hazard']:.3f}** in the less hazardous half.",
    ]
    for iso3 in ["FRA", "IND", "USA"]:
        if iso3 in key["h1"]:
            row = key["h1"][iso3]
            lines.append(f"- {iso3}: rho = {row['rho']:.2f} (p = {row['p_value']:.2g}, N = {row['n']}).")

    lines += [
        "",
        "## H2 - is it still true inside countries?",
        f"- Without country effects: coefficient **{m1['beta']:.2f}** "
        f"(95% CI {m1['ci'][0]:.2f} to {m1['ci'][1]:.2f}).",
        f"- With country effects: coefficient **{m2['beta']:.2f}** "
        f"(95% CI {m2['ci'][0]:.2f} to {m2['ci'][1]:.2f}, N = {m2['n']}).",
        "- The coefficient is the change in SHDI from the least to the most hazardous region.",
        "",
        "## H3 - is the ranking stable?",
        f"- Lowest Spearman correlation between two index versions: **{key['h3_min_rho']:.2f}**.",
        f"- At least **{key['h3_min_same_in_top10']}** of the top 10 regions are the same "
        "in every pair of versions.",
        "",
        "## Highest-risk regions",
        "",
    ]
    top = master.nlargest(10, "risk_equal")
    for i, (_, row) in enumerate(top.iterrows(), start=1):
        lines.append(f"{i}. {row['region_name']} ({row['country']}) - risk {row['risk_equal']:.3f}")

    lines += ["", "> These are associations, not causal effects. See the limitations section."]

    path = outputs / "report" / "key_results.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
