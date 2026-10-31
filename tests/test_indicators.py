"""Tests for the indicator maths.

Why these tests: the risk index is built from a chain of small steps
(ranks, means, products). A silent bug in one step would still produce a
pretty map, but the numbers would be wrong. These tests pin down the
behaviour on tiny hand-checked examples, so a change in the code that
breaks the logic is caught immediately.

Run them with:  pytest -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cro.features.build import build_exposure, build_hazard, build_vulnerability
from cro.utils import percentile_rank, weighted_mean


# ---------------------------------------------------------------------------
# Small helper functions
# ---------------------------------------------------------------------------

def test_percentile_rank_is_monotonic_and_bounded():
    """A bigger value must never get a smaller rank, and ranks stay in 0-1."""
    values = pd.Series([5, 1, 9, 3])
    ranks = percentile_rank(values)

    assert ranks.between(0, 1).all()
    # The largest value gets the highest rank, the smallest the lowest.
    assert ranks.iloc[2] == ranks.max()
    assert ranks.iloc[1] == ranks.min()


def test_percentile_rank_keeps_missing_values():
    """Missing data must stay missing instead of becoming a rank."""
    ranks = percentile_rank(pd.Series([1.0, np.nan, 3.0]))
    assert ranks.isna().sum() == 1
    assert ranks.notna().sum() == 2


def test_weighted_mean_ignores_missing_and_zero_weights():
    value = weighted_mean(pd.Series([1.0, 3.0, 100.0]),
                          pd.Series([1.0, 1.0, 0.0]))
    assert value == 2.0


# ---------------------------------------------------------------------------
# Hazard
# ---------------------------------------------------------------------------

@pytest.fixture()
def toy_climate() -> pd.DataFrame:
    """Four invented regions with easily checked climate profiles.

    desert    - very hot, very dry
    coast     - hardly hot, extremely wet
    temperate - mild
    cold      - cold and dry but not hot
    """
    return pd.DataFrame({
        "region_id": ["desert", "coast", "temperate", "cold"],
        "hd35_area": [180.0, 10.0, 5.0, 0.0],
        "tr25_area": [90.0, 120.0, 2.0, 0.0],
        "cdd_area": [200.0, 30.0, 20.0, 10.0],
        "wbal_area": [-1400.0, 1500.0, 200.0, 900.0],
        "rx1d_area": [20.0, 180.0, 40.0, 30.0],
        "r50_area": [0.0, 12.0, 2.0, 1.0],
    })


def test_hazard_components_are_bounded(toy_climate):
    """Every hazard score must be a 0-1 index, whatever the raw units."""
    result = build_hazard(toy_climate, cfg={})

    for column in ["hazard_heat", "hazard_dry", "hazard_wet", "hazard_equal"]:
        assert result[column].between(0, 1).all(), column
        assert result[column].notna().all(), column


def test_equal_hazard_is_the_mean_of_the_three_parts(toy_climate):
    """The headline index is defined as the mean of heat, dry and wet."""
    result = build_hazard(toy_climate, cfg={})

    expected = result[["hazard_heat", "hazard_dry", "hazard_wet"]].mean(axis=1)
    pd.testing.assert_series_equal(result["hazard_equal"], expected,
                                   check_names=False)


def test_desert_ranks_high_on_heat_and_dry_not_on_wet(toy_climate):
    """Sanity check that matches physical intuition.

    If a desert did not score high on heat and dryness, the index would be
    upside down and every result downstream would be meaningless.
    """
    result = build_hazard(toy_climate, cfg={}).set_index("region_id")

    assert result.loc["desert", "hazard_heat"] > result.loc["temperate", "hazard_heat"]
    assert result.loc["desert", "hazard_dry"] > result.loc["coast", "hazard_dry"]
    # The monsoon coast should be the wettest, so the highest wet score.
    assert result.loc["coast", "hazard_wet"] == result["hazard_wet"].max()


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------

def test_person_days_is_population_times_heat_days():
    """A hand-calculated example: 100 people x 10 days + 300 x 20 = 7,000."""
    point_year = pd.DataFrame({
        "point_id": ["p1", "p1", "p2", "p2"],
        "year": [2000, 2001, 2000, 2001],
        "hd35": [10.0, 10.0, 20.0, 20.0],
    })
    point_pop = pd.DataFrame({
        "point_id": ["p1", "p2"],
        "point_pop": [100.0, 300.0],
    })
    points = pd.DataFrame({
        "point_id": ["p1", "p2"],
        "region_id": ["r1", "r1"],
    })
    cfg = {"climate": {"baseline_start": 2000, "baseline_end": 2001}}

    result = build_exposure(point_year, point_pop, points, cfg)

    assert len(result) == 1
    assert result.loc[0, "person_days_heat"] == pytest.approx(7000.0)
    # 7,000 person-days over 400 people = 17.5 heat days per person.
    assert result.loc[0, "pop_weighted_hd35"] == pytest.approx(17.5)


# ---------------------------------------------------------------------------
# Vulnerability
# ---------------------------------------------------------------------------

def test_vulnerability_is_the_mirror_of_development():
    """Low SHDI must mean high vulnerability."""
    development = pd.DataFrame({
        "region_id": ["rich", "poor"],
        "indicator": ["shdi", "shdi"],
        "value": [0.95, 0.55],
        "year": [2020, 2020],
        "source": ["GDL", "GDL"],
        "match_score": [1.0, 0.9],
    })

    result = build_vulnerability(development).set_index("region_id")

    assert result.loc["poor", "vulnerability"] > result.loc["rich", "vulnerability"]
    # With two regions the ranks are 0.5 and 1.0, so vulnerability is 0.5 and 0.
    assert result.loc["poor", "vulnerability"] == pytest.approx(0.5)
    assert result.loc["rich", "vulnerability"] == pytest.approx(0.0)


def test_missing_development_stays_missing():
    """We do not fill missing SHDI with a country average.

    Regions without data must be dropped from the development models, not
    given an invented value, so this behaviour is part of the contract.
    """
    development = pd.DataFrame({
        "region_id": ["a", "b"],
        "indicator": ["shdi", "shdi"],
        "value": [0.8, np.nan],
        "year": [2020, 2020],
        "source": ["GDL", "GDL"],
        "match_score": [1.0, 0.0],
    })

    result = build_vulnerability(development).set_index("region_id")
    assert pd.isna(result.loc["b", "vulnerability"])


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def test_h1_finds_a_negative_link_on_toy_data():
    """More hazard and less SHDI must give a negative Spearman correlation."""
    from cro.analysis.tests import hazard_development_test

    data = pd.DataFrame({
        "hazard_equal": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        "shdi": [0.95, 0.90, 0.85, 0.80, 0.75, 0.70],
    })
    result = hazard_development_test(data, "toy")

    assert result["spearman_rho"] == pytest.approx(-1.0)
    assert result["median_shdi_high_hazard"] < result["median_shdi_low_hazard"]


def test_rank_stability_counts_the_shared_top_regions():
    """Two identical rankings must have rho = 1 and share their whole top 10."""
    from cro.analysis.tests import test_rank_stability as rank_stability

    ranks = list(range(1, 13))
    versions = pd.concat([
        pd.DataFrame({"region_id": [f"r{i}" for i in ranks], "rank": ranks, "version": "a"}),
        pd.DataFrame({"region_id": [f"r{i}" for i in ranks], "rank": ranks, "version": "b"}),
    ])
    result = rank_stability(versions)

    assert result.loc[0, "spearman_rho"] == pytest.approx(1.0)
    assert result.loc[0, "same_in_top10"] == 10
