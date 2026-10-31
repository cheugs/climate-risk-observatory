"""Data-contract checks.

A "data contract" is a short list of things that must be true for the
analysis to mean anything. Examples:
- every region appears once in the master table,
- the population counted per region and per sample point roughly agrees,
- hazard scores stay between 0 and 1.

If one of these breaks, the figures may still draw, but the numbers would
be wrong. So we check them on purpose, in one place.

Run it with:  cro validate
The command exits with code 1 if a hard check fails, which is useful in CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

from cro.config import load_config
from cro.utils import log


class Result:
    """One check: a name, PASS/FAIL, and a sentence explaining why."""

    def __init__(self, name: str, passed: bool, detail: str):
        self.name = name
        self.passed = passed
        self.detail = detail

    def __str__(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        return f"[{mark}] {self.name}: {self.detail}"


def _load(name: str) -> pd.DataFrame:
    """Load one processed file and give a clear error if it is missing."""
    cfg = load_config()
    path = Path(cfg["paths"]["processed"]) / name
    if not path.exists():
        raise FileNotFoundError(
            f"{name} is missing. Run the pipeline first: cro boundaries && ... "
            f"(or simply: cro all)"
        )
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_regions() -> Result:
    """Boundaries: unique ids, valid geometry, positive area."""
    regions = gpd.read_parquet(Path(load_config()["paths"]["processed"]) / "regions.parquet")

    duplicates = regions["region_id"].duplicated().sum()
    invalid = (~regions.geometry.is_valid).sum()
    empty = regions.geometry.is_empty.sum()
    bad_area = (regions["area_km2"] <= 0).sum()

    problems = []
    if duplicates:
        problems.append(f"{duplicates} duplicate region_id")
    if invalid:
        problems.append(f"{invalid} invalid geometries")
    if empty:
        problems.append(f"{empty} empty geometries")
    if bad_area:
        problems.append(f"{bad_area} regions with non-positive area")

    detail = (f"{len(regions)} regions, {regions['iso3'].nunique()} countries, "
              f"CRS {regions.crs.to_string() if regions.crs else 'none'}"
              if not problems else "; ".join(problems))
    return Result("boundaries", not problems, detail)


def check_sample_points() -> Result:
    """Every region should have at least one climate sample point."""
    points = _load("climate_points.parquet")
    regions = _load("regions.parquet")

    covered = set(points["region_id"])
    missing = set(regions["region_id"]) - covered
    inside = points["lon"].between(-180, 180) & points["lat"].between(-90, 90)

    passed = not missing and bool(inside.all())
    detail = f"{len(points)} points covering {len(covered)}/{len(regions)} regions"
    if missing:
        detail += f"; {len(missing)} regions uncovered"
    if not inside.all():
        detail += f"; {(~inside).sum()} points outside valid lon/lat"
    return Result("climate sample points", passed, detail)


def check_population_reconciles() -> Result:
    """Region totals and point totals should agree within 5%.

    They are computed in two different ways (polygon mask vs nearest-point
    assignment), so a small difference is expected. A large one means the
    population weights are wrong.
    """
    regions = _load("population_regions.parquet")
    points = _load("point_population.parquet")

    region_total = regions["population"].sum()
    point_total = points["point_pop"].sum()
    difference = abs(point_total - region_total) / region_total

    passed = difference <= 0.05
    detail = (f"region total {region_total / 1e6:,.1f}M vs point total "
              f"{point_total / 1e6:,.1f}M ({difference:.1%} difference)")
    return Result("population reconciles", passed, detail)


def check_climate_ranges() -> Result:
    """Physical limits for the hazard indicators."""
    climate = _load("climate_regions.parquet")

    checks = {
        "hd35_area": (0, 366, "heat days"),
        "tr25_area": (0, 366, "tropical nights"),
        "cdd_area": (0, 366, "dry spell length"),
        "wbal_area": (-3000, 5000, "water balance (mm)"),
        "rx1d_area": (0, 2000, "daily rainfall (mm)"),
        "r50_area": (0, 366, "very wet days"),
    }

    problems = []
    for column, (low, high, label) in checks.items():
        values = climate[column].dropna()
        outside = ((values < low) | (values > high)).sum()
        if outside:
            problems.append(f"{outside} {label} values outside {low}..{high}")
    missing = climate["hd35_area"].isna().sum()
    if missing:
        problems.append(f"{missing} regions without heat-day values")

    detail = (f"{len(climate)} regions checked" if not problems else "; ".join(problems))
    return Result("climate ranges", not problems, detail)


def check_scores_bounded() -> Result:
    """Indices must stay between 0 and 1."""
    master = _load("region_master.parquet")
    columns = ["hazard_heat", "hazard_dry", "hazard_wet", "hazard_equal",
               "exposure_score", "vulnerability", "risk_equal", "risk_additive",
               "risk_per_person"]

    problems = []
    for column in columns:
        if column not in master.columns:
            problems.append(f"{column} missing")
            continue
        values = master[column].dropna()
        if ((values < 0) | (values > 1)).any():
            problems.append(f"{column} outside 0..1")

    return Result("index bounds", not problems,
                  "all index columns within 0..1" if not problems else "; ".join(problems))


def check_master_unique() -> Result:
    """One row per region in the analysis table."""
    master = _load("region_master.parquet")
    regions = _load("regions.parquet")

    duplicates = master["region_id"].duplicated().sum()
    missing = len(set(regions["region_id"]) - set(master["region_id"]))

    passed = duplicates == 0 and missing == 0
    detail = f"{len(master)} rows, {duplicates} duplicates, {missing} regions missing"
    return Result("master table", passed, detail)


def check_development_coverage() -> Result:
    """Report (but do not fail) how much subnational development data we have.

    Missing SHDI for a few small territories is expected, so this is a
    warning rather than an error. We still print it because the report must
    say how many regions were left out of the development models.
    """
    master = _load("region_master.parquet")
    coverage = master["shdi"].notna().sum() / len(master)

    # 80% coverage is the threshold we set ourselves before starting.
    passed = coverage >= 0.80
    detail = (f"SHDI available for {master['shdi'].notna().sum()}/{len(master)} "
              f"regions ({coverage:.0%})")
    return Result("development coverage", passed, detail)


def check_tables_written() -> Result:
    """Every expected output table should exist and have rows."""
    cfg = load_config()
    tables = Path(cfg["paths"]["outputs"]) / "tables"

    expected = [
        "t01_summary_by_country.csv", "t02_climate_by_country.csv",
        "t03_top_bottom_regions.csv", "t05_hypothesis_tests.csv",
        "t06_rank_stability.csv", "t07_regression_coefficients.csv",
        "t08_country_slopes.csv",
    ]

    missing = [name for name in expected if not (tables / name).exists()]
    empty = [name for name in expected
             if (tables / name).exists() and len(pd.read_csv(tables / name)) == 0]

    problems = [f"missing {name}" for name in missing] + [f"empty {name}" for name in empty]
    return Result("output tables", not problems,
                  f"{len(expected)} tables present" if not problems else "; ".join(problems))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> list[Result]:
    """Run every check, print the results and return them."""
    checks = [
        check_regions,
        check_sample_points,
        check_population_reconciles,
        check_climate_ranges,
        check_scores_bounded,
        check_master_unique,
        check_development_coverage,
        check_tables_written,
    ]

    results = []
    for check in checks:
        try:
            result = check()
        except Exception as error:
            # A crashed check is a failure, not a crash of the validator.
            result = Result(check.__name__.replace("check_", ""), False, str(error)[:160])
        results.append(result)
        log(f"validate: {result}")

    failed = [r for r in results if not r.passed]

    # Save a small markdown summary so the report can quote it.
    cfg = load_config()
    report_dir = Path(cfg["paths"]["outputs"]) / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# Data checks", "",
             f"- Checks run: **{len(results)}**",
             f"- Passed: **{len(results) - len(failed)}**",
             f"- Failed: **{len(failed)}**", ""]
    for result in results:
        mark = "PASS" if result.passed else "FAIL"
        lines.append(f"- `{mark}` **{result.name}** - {result.detail}")
    (report_dir / "validation.md").write_text("\n".join(lines), encoding="utf-8")

    log(f"validate: {len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        # Exit code 1 lets a script or CI job notice the problem.
        sys.exit(1)
    return results


if __name__ == "__main__":
    run()
