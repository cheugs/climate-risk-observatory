"""Quick health check of every data source we depend on.

Why this file exists: a project that downloads from five different websites
breaks when one of them changes. Before blaming our own code, we want to be
able to answer "is the source down, or is it us?".

Run it with:  cro probe

Each check prints one line: OK, WARN or FAIL. Nothing is downloaded to disk,
so the probe is safe to run any time.
"""

from __future__ import annotations

from pathlib import Path

import requests

from cro.config import load_config
from cro.utils import log

# A short timeout: if a service takes longer than this, it is probably down.
TIMEOUT = 30


def check_nasa_power() -> tuple[str, str]:
    """NASA POWER: can we still get a single day of temperature?"""
    url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {
        "parameters": "T2M_MAX",
        "community": "AG",
        "longitude": 2.35,
        "latitude": 48.85,
        "start": "20200101",
        "end": "20200102",
        "format": "JSON",
    }
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
        if response.status_code != 200:
            return "FAIL", f"HTTP {response.status_code}"
        data = response.json()["properties"]["parameter"]["T2M_MAX"]
        return "OK", f"{len(data)} daily value(s) returned"
    except Exception as error:
        return "FAIL", str(error)[:90]


def check_geoboundaries() -> tuple[str, str]:
    """geoBoundaries: is the ADM1 API for our pilot still there?"""
    url = "https://www.geoboundaries.org/api/current/gbOpen/IND/ADM1/"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code != 200:
            return "FAIL", f"HTTP {response.status_code}"
        meta = response.json()
        # The API sometimes returns a list with one element.
        if isinstance(meta, list):
            meta = meta[0]
        return "OK", f"{meta.get('boundaryName', 'unknown')} ADM1"
    except Exception as error:
        return "FAIL", str(error)[:90]


def check_world_bank() -> tuple[str, str]:
    """World Bank: one indicator, one country, two pages of JSON."""
    url = "https://api.worldbank.org/v2/country/IND/indicator/SP.DYN.LE00.IN"
    params = {"format": "json", "per_page": 5}
    try:
        response = requests.get(url, params=params, timeout=TIMEOUT)
        if response.status_code != 200:
            return "FAIL", f"HTTP {response.status_code}"
        payload = response.json()
        if not isinstance(payload, list) or len(payload) < 2:
            return "FAIL", "unexpected JSON shape"
        values = [row for row in (payload[1] or []) if row.get("value") is not None]
        return "OK", f"{len(values)} non-empty value(s)"
    except Exception as error:
        return "FAIL", str(error)[:90]


def check_global_data_lab() -> tuple[str, str]:
    """Global Data Lab: does the SHDI table page still load?"""
    url = "https://globaldatalab.org/shdi/table/shdi/IND/"
    try:
        response = requests.get(url, timeout=TIMEOUT,
                                headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code != 200:
            return "FAIL", f"HTTP {response.status_code}"
        if "<table" not in response.text:
            return "WARN", "page loaded but no table found"
        return "OK", f"{len(response.text) // 1024} KB page"
    except Exception as error:
        return "FAIL", str(error)[:90]


def check_ghs_pop() -> tuple[str, str]:
    """GHS-POP: is the big raster already on disk?

    We do not re-download 482 MB just to run a probe, so this is a local
    check only.
    """
    cfg = load_config()
    zip_path = Path(cfg["paths"]["raw"]) / "GHS_POP_E2020.zip"
    tif_dir = Path(cfg["paths"]["raw"]) / "ghs_pop"
    tifs = list(tif_dir.glob("*.tif"))

    if tifs:
        size_mb = tifs[0].stat().st_size / 1e6
        return "OK", f"{tifs[0].name} ({size_mb:,.0f} MB)"
    if zip_path.exists():
        return "WARN", "archive present but not extracted yet"
    return "FAIL", "GHS_POP_E2020.zip not found in data/raw/"


def check_outputs() -> tuple[str, str]:
    """Do we have the intermediate files the later steps need?"""
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    required = [
        "regions.parquet", "climate_points.parquet", "point_population.parquet",
        "climate_point_year.parquet", "region_master.parquet",
    ]
    missing = [name for name in required if not (processed / name).exists()]
    if missing:
        return "WARN", "missing: " + ", ".join(missing)
    return "OK", f"{len(required)} key files present"


def run() -> list[tuple[str, str, str]]:
    """Run every probe and print a small table."""
    checks = [
        ("NASA POWER", check_nasa_power),
        ("geoBoundaries", check_geoboundaries),
        ("World Bank WDI", check_world_bank),
        ("Global Data Lab", check_global_data_lab),
        ("GHS-POP raster", check_ghs_pop),
        ("Pipeline outputs", check_outputs),
    ]

    results = []
    for name, function in checks:
        status, detail = function()
        results.append((name, status, detail))
        log(f"probe: {name:<16} {status:<4} {detail}")

    failures = [row for row in results if row[1] == "FAIL"]
    if failures:
        log(f"probe: {len(failures)} source(s) failed. Check your connection "
            f"or whether the service changed its API.")
    else:
        log("probe: all sources reachable")
    return results


if __name__ == "__main__":
    run()
