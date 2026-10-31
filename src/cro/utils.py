"""Small helper functions used everywhere in the project.

Nothing clever lives here: logging, file helpers, HTTP retries, and the
normalisation functions used to build indices.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(message: str) -> None:
    """Print a message with a timestamp so long downloads are easy to follow."""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def save_table(df: pd.DataFrame, path: Path, index: bool = False) -> None:
    """Save a table as Parquet (small and fast) and create folders if needed.

    GeoDataFrames are saved with GeoPandas so the geometry column keeps its
    special type. Plain DataFrames use normal Parquet.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # GeoDataFrame.to_parquet writes GeoParquet; DataFrame.to_parquet writes
    # a normal table. Both accept the same arguments, so one call covers both.
    df.to_parquet(path, index=index)
    log(f"saved {len(df):,} rows -> {path}")


def load_geo_table(path: Path, geometry: str = "geometry",
                   crs: str = "EPSG:4326"):
    """Read a Parquet table that contains a geometry column.

    A geometry column can come back in two different shapes depending on how
    the file was written:

    - shapely objects, if the file is proper GeoParquet,
    - raw WKB bytes, if the geometry was written by plain pandas.

    Plotting only works with the first, so this helper turns the second into
    the first. It keeps the fix in one place instead of repeating it in every
    map function.
    """
    import geopandas as gpd

    frame = pd.read_parquet(path)
    if frame.empty:
        return gpd.GeoDataFrame(frame, geometry=geometry, crs=crs)

    first_value = frame[geometry].iloc[0]
    if isinstance(first_value, (bytes, bytearray)):
        # WKB bytes -> shapely points/polygons.
        frame[geometry] = gpd.GeoSeries.from_wkb(frame[geometry], crs=crs)

    if not isinstance(frame, gpd.GeoDataFrame):
        frame = gpd.GeoDataFrame(frame, geometry=geometry, crs=crs)
    elif frame.crs is None:
        frame = frame.set_crs(crs)
    return frame


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def get_json(url: str, params: dict | None = None, retries: int = 5,
             pause: float = 2.0, timeout: int = 90) -> Any:
    """GET a URL and return JSON, retrying on temporary errors.

    Free APIs sometimes answer 429 (too many requests). Instead of crashing
    the whole pipeline we wait a little longer each time and try again.
    """
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            if response.status_code == 200:
                return response.json()
            # 429 and 5xx errors are worth retrying; 4xx usually are not.
            if response.status_code == 429 or response.status_code >= 500:
                wait = pause * attempt
                log(f"HTTP {response.status_code} from {url[:60]}..., retry in {wait:.0f}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
        except requests.RequestException as error:
            wait = pause * attempt
            log(f"request failed ({error}), retry in {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"Could not download {url} after {retries} attempts")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def percentile_rank(series: pd.Series) -> pd.Series:
    """Convert values to a 0-1 score based on their rank.

    Percentile ranks are used instead of min-max scaling because climate
    indicators have extreme outliers (a desert is much drier than a
    rainforest). Ranks keep one outlier from squashing everything else.
    Missing values stay missing.
    """
    return series.rank(pct=True, na_option="keep")


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    """Mean of `values` where each value counts according to `weights`."""
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return np.nan
    return float(np.average(values[mask], weights=weights[mask]))
