"""Data-contract tests against the real pipeline outputs.

These tests are deliberately different from `tests/test_indicators.py`:
they do not test the maths on toy data, they check that the files actually
on disk still satisfy the promises the analysis relies on.

They are skipped when the pipeline has not been run yet, so a fresh clone
can still run `pytest` without downloading 500 MB of data first.

Run them with:  pytest -q
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cro.config import load_config
from cro import validate


PROCESSED = Path(load_config()["paths"]["processed"])
NEEDED = ["regions.parquet", "region_master.parquet", "climate_regions.parquet"]

pytestmark = pytest.mark.skipif(
    not all((PROCESSED / name).exists() for name in NEEDED),
    reason="pipeline outputs not built yet (run `cro all`)",
)


def test_master_has_one_row_per_region():
    master = pd.read_parquet(PROCESSED / "region_master.parquet")
    regions = pd.read_parquet(PROCESSED / "regions.parquet")

    assert master["region_id"].is_unique
    assert set(regions["region_id"]) == set(master["region_id"])


def test_indices_stay_between_zero_and_one():
    master = pd.read_parquet(PROCESSED / "region_master.parquet")
    columns = [c for c in ["hazard_equal", "exposure_score", "vulnerability",
                           "risk_equal", "risk_additive", "risk_per_person"]
               if c in master.columns]

    assert columns, "no index columns found"
    for column in columns:
        values = master[column].dropna()
        assert values.between(0, 1).all(), column


def test_risk_is_made_of_its_three_parts():
    """Risk must equal hazard x exposure x vulnerability, not something else."""
    master = pd.read_parquet(PROCESSED / "region_master.parquet")
    data = master.dropna(subset=["hazard_equal", "exposure_score", "vulnerability"])

    expected = data["hazard_equal"] * data["exposure_score"] * data["vulnerability"]
    assert (data["risk_equal"] - expected).abs().max() < 1e-12


def test_exposure_uses_population_only():
    """Exposure is the population rank, so heat is not counted twice."""
    master = pd.read_parquet(PROCESSED / "region_master.parquet")
    expected = master["population"].rank(pct=True)
    assert (master["exposure_score"] - expected).abs().max() < 1e-12


def test_population_reconciles_between_two_methods():
    """Polygon sums and nearest-point assignment should agree within 5%."""
    regions = pd.read_parquet(PROCESSED / "population_regions.parquet")
    points = pd.read_parquet(PROCESSED / "point_population.parquet")

    difference = abs(points["point_pop"].sum() - regions["population"].sum())
    assert difference / regions["population"].sum() < 0.05


def test_every_region_has_a_climate_sample_point():
    points = pd.read_parquet(PROCESSED / "climate_points.parquet")
    regions = pd.read_parquet(PROCESSED / "regions.parquet")

    assert set(regions["region_id"]) - set(points["region_id"]) == set()


def test_validation_checks_all_pass():
    """The user-facing validator is the same list of promises, so run it.

    `validate.run()` calls `sys.exit(1)` when a check fails, which pytest
    would report as an error rather than a normal failure. We catch that and
    turn it into a readable assertion message.
    """
    try:
        results = validate.run()
    except SystemExit:
        pytest.fail("`cro validate` reported at least one failing check")

    failed = [str(result) for result in results if not result.passed]
    assert not failed, "failed checks:\n" + "\n".join(failed)
