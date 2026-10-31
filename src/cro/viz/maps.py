"""Static maps.

The pilot covers three countries that are far apart, so a single world map
would waste most of the space. Instead every map has three panels: France,
India and the United States, each zoomed to its own area but sharing one
colour scale so they can be compared fairly.

Alaska, Hawaii and the US island territories are included in the analysis
but left out of the *drawing* of the US panel, because otherwise the
mainland would be a tiny speck. The note under each map says so.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.patches import Patch

from cro.viz import theme

COUNTRY_ORDER = ["FRA", "IND", "USA"]
COUNTRY_NAMES = {"FRA": "France", "IND": "India", "USA": "United States"}

# Fixed display windows (minx, miny, maxx, maxy) so every map lines up.
DISPLAY_BOUNDS = {
    "FRA": (-5.5, 41.0, 9.8, 51.3),
    "IND": (67.5, 7.5, 97.5, 35.5),
    "USA": (-125.5, 24.0, -66.5, 49.5),
}


def _panel_data(gdf: gpd.GeoDataFrame, iso3: str) -> gpd.GeoDataFrame:
    """All regions of a country (the analysis uses all of them)."""
    return gdf[gdf["iso3"] == iso3]


def _draw_panel(ax, gdf, iso3, column, cmap, norm):
    """Draw one country panel."""
    data = _panel_data(gdf, iso3)
    data.plot(
        column=column, ax=ax, cmap=cmap, norm=norm,
        edgecolor="white", linewidth=0.35,
        missing_kwds={"color": "#ececec", "hatch": "///", "edgecolor": "white"},
    )
    ax.set_xlim(DISPLAY_BOUNDS[iso3][0], DISPLAY_BOUNDS[iso3][2])
    ax.set_ylim(DISPLAY_BOUNDS[iso3][1], DISPLAY_BOUNDS[iso3][3])
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(COUNTRY_NAMES[iso3], loc="left")


def indicator_map(gdf: gpd.GeoDataFrame, column: str, title: str, cmap: str,
                  path: Path, label: str, note: str | None = None,
                  vmin: float | None = None, vmax: float | None = None) -> None:
    """Three-panel choropleth for one indicator."""
    theme.apply_style()
    values = gdf[column].dropna()
    if vmin is None:
        vmin = float(values.quantile(0.02))
    if vmax is None:
        vmax = float(values.quantile(0.98))

    norm = Normalize(vmin=vmin, vmax=vmax)
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2))

    for ax, iso3 in zip(axes, COUNTRY_ORDER):
        _draw_panel(ax, gdf, iso3, column, cmap, norm)

    fig.suptitle(title, x=0.01, ha="left", fontsize=15, fontweight="bold")
    colorbar = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=axes,
                            orientation="horizontal", fraction=0.035, pad=0.02,
                            aspect=60)
    colorbar.set_label(label)

    if note is None:
        note = ("US panel shows the contiguous states; Alaska, Hawaii and island "
                "territories are included in the statistics but not drawn.")
    theme.save_figure(fig, path, note=note)


def double_exposure_map(master: gpd.GeoDataFrame, path: Path) -> None:
    """Map regions that are both high hazard and low development.

    We split hazard and development at their medians. The top-right group
    (high hazard, low development) is the priority group for adaptation.
    """
    theme.apply_style()
    data = master.dropna(subset=["hazard_equal", "vulnerability"]).copy()
    hazard_cut = data["hazard_equal"].median()
    vuln_cut = data["vulnerability"].median()

    def group(row):
        """Return the map group of one region (hazard and vulnerability vs medians)."""
        high_hazard = row["hazard_equal"] > hazard_cut
        high_vuln = row["vulnerability"] > vuln_cut
        if high_hazard and high_vuln:
            return "high hazard + low development"
        if high_hazard:
            return "high hazard only"
        if high_vuln:
            return "low development only"
        return "lower hazard + higher development"

    data["double_group"] = data.apply(group, axis=1)
    colors = {
        "high hazard + low development": "#b2182b",
        "high hazard only": "#ef8a62",
        "low development only": "#67a9cf",
        "lower hazard + higher development": "#e6e6e6",
    }

    fig, axes = plt.subplots(1, 3, figsize=(17, 5.2))
    for ax, iso3 in zip(axes, COUNTRY_ORDER):
        subset = data[data["iso3"] == iso3]
        subset.plot(ax=ax, color="#f2f2f2", edgecolor="white", linewidth=0.3)
        for label, color in colors.items():
            part = subset[subset["double_group"] == label]
            if part.empty:
                continue
            part.plot(ax=ax, color=color, edgecolor="white", linewidth=0.3)
        ax.set_xlim(DISPLAY_BOUNDS[iso3][0], DISPLAY_BOUNDS[iso3][2])
        ax.set_ylim(DISPLAY_BOUNDS[iso3][1], DISPLAY_BOUNDS[iso3][3])
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_title(COUNTRY_NAMES[iso3], loc="left")

    legend = [Patch(facecolor=color, label=label) for label, color in colors.items()]
    fig.legend(handles=legend, loc="lower center", ncol=4, fontsize=8,
               bbox_to_anchor=(0.5, -0.02))
    fig.suptitle("Double exposure: high climate hazard and low development",
                 x=0.01, ha="left", fontsize=15, fontweight="bold")
    theme.save_figure(fig, path)


def plot_all(master: gpd.GeoDataFrame, maps_dir: Path) -> list[Path]:
    """Create every static map and return the file paths."""
    maps_dir.mkdir(parents=True, exist_ok=True)
    outputs = []

    # The master table has no geometry, so attach it to the region polygons.
    gdf = master.copy()
    if "geometry" not in gdf.columns:
        regions = gpd.read_parquet(Path("data/processed/regions.parquet"))
        gdf = regions[["region_id", "geometry"]].merge(gdf, on="region_id", how="left")
        gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")

    specs = [
        ("hazard_equal", "Climate hazard index", theme.CMAP_HAZARD,
         "hazard index (0-1)", "map_01_hazard.png", 0, 1),
        ("hazard_heat", "Heat hazard", theme.CMAP_HAZARD,
         "heat sub-index (0-1)", "map_02_heat.png", 0, 1),
        ("hazard_dry", "Dry hazard", theme.CMAP_HAZARD,
         "dry sub-index (0-1)", "map_03_dry.png", 0, 1),
        ("hazard_wet", "Wet hazard", theme.CMAP_HAZARD,
         "wet sub-index (0-1)", "map_04_wet.png", 0, 1),
        ("hd35_area", "Days above 35 C", "YlOrRd",
         "days per year (2004-2023 mean)", "map_05_heat_days.png", None, None),
        ("exposure_score", "Exposure (population)", theme.CMAP_EXPOSURE,
         "exposure score (0-1, percentile of population)", "map_06_exposure.png", 0, 1),
        ("shdi", "Subnational Human Development Index", theme.CMAP_DEVELOPMENT,
         "SHDI (latest year)", "map_07_shdi.png", None, None),
        ("vulnerability", "Vulnerability (1 - development score)", "viridis_r",
         "vulnerability (0-1)", "map_08_vulnerability.png", 0, 1),
        ("risk_equal", "Composite climate risk", theme.CMAP_RISK,
         "risk index (0-1, higher = more risk)", "map_09_risk.png", 0, 1),
        ("risk_per_person", "Risk without population (hazard x vulnerability)",
         theme.CMAP_RISK, "risk per person (0-1)", "map_10_risk_per_person.png", 0, 1),
    ]

    for column, title, cmap, label, filename, vmin, vmax in specs:
        if column not in gdf.columns:
            continue
        path = maps_dir / filename
        indicator_map(gdf, column, title, cmap, path, label, vmin=vmin, vmax=vmax)
        outputs.append(path)

    path = maps_dir / "map_11_double_exposure.png"
    double_exposure_map(gdf, path)
    outputs.append(path)

    return outputs
