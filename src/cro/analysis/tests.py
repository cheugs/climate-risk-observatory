"""Hypothesis tests H1 and H3.

The project asks three questions:

H1  Do regions with more climate hazard have lower human development?
H2  Is this still true when we compare regions inside the same country?
    (see regression.py)
H3  Is the risk ranking stable when we change how the index is built?

For H1 we use the Spearman rank correlation. It works on ranks, so it does
not need a normal distribution and it is not affected by a few extreme
values. We run it on all regions together and then country by country,
because a correlation on all regions can simply reflect the difference
between India and the two other countries.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy import stats

from cro.config import load_config
from cro.utils import log, save_table


# ---------------------------------------------------------------------------
# H1: hazard and development
# ---------------------------------------------------------------------------

def hazard_development_test(data: pd.DataFrame, group: str) -> dict:
    """Spearman correlation between hazard and SHDI for one group of regions.

    We also split the regions at the median hazard and compare the median
    SHDI of the two halves. This is easier to explain than a correlation.
    """
    data = data.dropna(subset=["hazard_equal", "shdi"])
    rho, p_value = stats.spearmanr(data["hazard_equal"], data["shdi"])

    median_hazard = data["hazard_equal"].median()
    high = data[data["hazard_equal"] > median_hazard]
    low = data[data["hazard_equal"] <= median_hazard]

    return {
        "group": group,
        "n_regions": len(data),
        "spearman_rho": float(rho),
        "p_value": float(p_value),
        "median_shdi_high_hazard": float(high["shdi"].median()),
        "median_shdi_low_hazard": float(low["shdi"].median()),
    }


def test_h1(master: pd.DataFrame) -> pd.DataFrame:
    """H1 on all regions, then inside each country."""
    rows = [hazard_development_test(master, "ALL")]
    for iso3, group in master.groupby("iso3"):
        rows.append(hazard_development_test(group, iso3))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# H3: is the ranking stable?
# ---------------------------------------------------------------------------

def test_rank_stability(versions: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Compare the ranking of every pair of index versions.

    Two numbers for each pair:
    - the Spearman correlation of the ranks (1 = exactly the same order);
    - how many regions are in the top 10 of both versions.
    """
    wide = versions.pivot(index="region_id", columns="version", values="rank")
    names = wide.columns.tolist()

    rows = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            pair = wide[[first, second]].dropna()
            rho, _ = stats.spearmanr(pair[first], pair[second])
            top_first = set(pair[first].nsmallest(top_n).index)
            top_second = set(pair[second].nsmallest(top_n).index)
            rows.append({
                "version_a": first,
                "version_b": second,
                "n_regions": len(pair),
                "spearman_rho": rho,
                f"same_in_top{top_n}": len(top_first & top_second),
            })

    return pd.DataFrame(rows).round(4)


def run() -> dict:
    """Run the H1 and H3 tests and save tables t05 and t06."""
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    tables = Path(cfg["paths"]["outputs"]) / "tables"

    master = pd.read_parquet(processed / "region_master.parquet")
    versions = pd.read_parquet(processed / "risk_versions.parquet")

    h1 = test_h1(master)
    save_table(h1, processed / "test_results.parquet")
    h1.to_csv(tables / "t05_hypothesis_tests.csv", index=False)

    stability = test_rank_stability(versions)
    save_table(stability, processed / "rank_stability.parquet")
    stability.to_csv(tables / "t06_rank_stability.csv", index=False)

    log("tests: H1 and H3 complete")
    return {"h1": h1, "stability": stability}


if __name__ == "__main__":
    run()
