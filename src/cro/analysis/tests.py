"""Hypothesis tests.

Each test answers one question from the project brief:

H1  Is climate exposure concentrated in a minority of regions?
H2  Do high-hazard regions have lower development?
H3  Does the hazard-development gap survive comparing regions *within*
    the same country? (done in regression.py)
H4  Are hazard and development spatially clustered? (done in spatial.py)
H5  Are the region rankings robust to the way the index is built?

We report effect sizes, not only p-values, because a p-value tells you
whether a difference is likely to be real, not how large it is.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from cro.config import load_config
from cro.utils import log, save_table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cliffs_delta(x: np.ndarray, y: np.ndarray) -> float:
    """Effect size for a Mann-Whitney test.

    Rough guide: |d| < 0.15 negligible, < 0.33 small, < 0.47 medium,
    otherwise large. +1 means every value in x is above every value in y.
    """
    x = np.asarray(x)
    y = np.asarray(y)
    # Compare every x with every y (fine for a few hundred regions).
    greater = (x[:, None] > y[None, :]).sum()
    smaller = (x[:, None] < y[None, :]).sum()
    return float((greater - smaller) / (len(x) * len(y)))


def bootstrap_ci(values: np.ndarray, statistic, iterations: int, seed: int,
                 alpha: float = 0.05) -> tuple[float, float]:
    """Percentile bootstrap confidence interval."""
    rng = np.random.default_rng(seed)
    estimates = []
    for _ in range(iterations):
        sample = rng.choice(values, size=len(values), replace=True)
        estimates.append(statistic(sample))
    return tuple(np.percentile(estimates, [100 * alpha / 2, 100 * (1 - alpha / 2)]))


# ---------------------------------------------------------------------------
# H1: concentration of exposure
# ---------------------------------------------------------------------------

def test_concentration(master: pd.DataFrame, cfg: dict) -> dict:
    """What share of person-days of heat sits in the top 10% of regions?

    We compare that share with the share of population in the same regions.
    A ratio above 1 means the most hazardous regions carry more than their
    fair share of exposure.
    """
    data = master.dropna(subset=["hazard_equal", "person_days_heat", "population"]).copy()
    data = data.sort_values("hazard_equal", ascending=False).reset_index(drop=True)

    top_n = max(1, int(round(len(data) * 0.10)))
    top = data.head(top_n)

    person_days_share = top["person_days_heat"].sum() / data["person_days_heat"].sum()
    population_share = top["population"].sum() / data["population"].sum()

    # Bootstrap over regions to get a confidence interval for the ratio.
    ratio = person_days_share / population_share
    rng = np.random.default_rng(cfg["analysis"]["random_seed"])
    ratios = []
    for _ in range(cfg["analysis"]["bootstrap_iterations"]):
        sample = data.sample(len(data), replace=True, random_state=int(rng.integers(1e9)))
        sample = sample.sort_values("hazard_equal", ascending=False)
        n = max(1, int(round(len(sample) * 0.10)))
        ratios.append(
            (sample.head(n)["person_days_heat"].sum() / sample["person_days_heat"].sum())
            / (sample.head(n)["population"].sum() / sample["population"].sum())
        )

    low, high = np.percentile(ratios, [2.5, 97.5])

    return {
        "hypothesis": "H1: exposure is concentrated in the most hazardous regions",
        "test": "share of person-days in top 10% hazard regions vs population share",
        "n_regions": len(data),
        "top_region_share_person_days": person_days_share,
        "top_region_share_population": population_share,
        "concentration_ratio": ratio,
        "ci_low": low,
        "ci_high": high,
        "p_value": None,
    }


# ---------------------------------------------------------------------------
# H2: hazard and development
# ---------------------------------------------------------------------------

def test_hazard_development(master: pd.DataFrame, cfg: dict) -> dict:
    """Do high-hazard regions have lower SHDI than low-hazard regions?

    We split regions at the median hazard, compare the two SHDI groups with
    a Mann-Whitney U test (which does not assume a normal distribution), and
    report Cliff's delta as the effect size.
    """
    data = master.dropna(subset=["hazard_equal", "shdi"]).copy()
    median = data["hazard_equal"].median()
    high = data.loc[data["hazard_equal"] > median, "shdi"].to_numpy()
    low = data.loc[data["hazard_equal"] <= median, "shdi"].to_numpy()

    u_stat, p_value = stats.mannwhitneyu(high, low, alternative="two-sided")

    # Also report the simple correlation with a confidence interval.
    rho, rho_p = stats.spearmanr(data["hazard_equal"], data["shdi"])

    return {
        "hypothesis": "H2: high-hazard regions have lower development",
        "test": "Mann-Whitney U on SHDI (high vs low hazard) + Spearman correlation",
        "n_regions": len(data),
        "n_high_hazard": len(high),
        "n_low_hazard": len(low),
        "median_shdi_high_hazard": float(np.median(high)),
        "median_shdi_low_hazard": float(np.median(low)),
        "u_statistic": float(u_stat),
        "p_value": float(p_value),
        "cliffs_delta": cliffs_delta(high, low),
        "spearman_rho": float(rho),
        "spearman_p": float(rho_p),
    }


# ---------------------------------------------------------------------------
# H5: robustness of the ranking
# ---------------------------------------------------------------------------

def test_rank_stability(versions: pd.DataFrame) -> pd.DataFrame:
    """Compare region rankings across index versions.

    If the top regions change completely when we switch from equal weights
    to PCA weights, the ranking is not trustworthy. We report the Spearman
    correlation between every pair of versions.
    """
    wide = versions.pivot(index="region_id", columns="version", values="rank")
    names = wide.columns.tolist()

    rows = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            pair = wide[[first, second]].dropna()
            rho, p_value = stats.spearmanr(pair[first], pair[second])
            rows.append({
                "version_a": first,
                "version_b": second,
                "n_regions": len(pair),
                "spearman_rho": rho,
                "p_value": p_value,
            })

    return pd.DataFrame(rows).round(4)


def top_regions_overlap(versions: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    """How many regions appear in the top `n` under every version?"""
    tops = {
        version: set(group.nsmallest(n, "rank")["region_id"])
        for version, group in versions.groupby("version")
    }
    names = list(tops)
    rows = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            overlap = len(tops[first] & tops[second])
            rows.append({
                "version_a": first,
                "version_b": second,
                f"overlap_top{n}": overlap,
                "share": round(overlap / n, 3),
            })
    return pd.DataFrame(rows)


def run() -> dict:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    tables = Path(cfg["paths"]["outputs"]) / "tables"

    master = pd.read_parquet(processed / "region_master.parquet")
    versions = pd.read_parquet(processed / "risk_versions.parquet")

    results = [test_concentration(master, cfg), test_hazard_development(master, cfg)]

    # Turn the list of dicts into a tidy table. Some tests leave p_value empty,
    # so we make sure the column exists before saving.
    tests = pd.DataFrame(results)
    if "p_value" not in tests.columns:
        tests["p_value"] = np.nan
    save_table(tests, processed / "test_results.parquet")
    tests.to_csv(tables / "t05_hypothesis_tests.csv", index=False)

    stability = test_rank_stability(versions)
    save_table(stability, processed / "rank_stability.parquet")
    stability.to_csv(tables / "t06_rank_stability.csv", index=False)

    overlap = top_regions_overlap(versions)
    save_table(overlap, processed / "top_overlap.parquet")

    log("tests: H1 and H2 complete")
    return {"tests": tests, "stability": stability, "overlap": overlap}


if __name__ == "__main__":
    run()
