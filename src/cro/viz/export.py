"""Export every output: static maps, statistical figures, interactive maps.

The static PNGs go in the report. The HTML maps can be opened in a browser
without running Python, which is useful for a portfolio.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import plotly.express as px

from cro.config import load_config
from cro.utils import load_geo_table, log
from cro.viz import charts, maps


def interactive_map(gdf: gpd.GeoDataFrame, column: str, path: Path, title: str,
                    label: str, colorscale: str = "YlOrRd") -> None:
    """Write one self-contained interactive choropleth as HTML."""
    data = gdf.dropna(subset=[column]).copy()

    # Simplify the geometry so the HTML file stays small and the browser
    # stays responsive. 0.02 degrees is about 2 km.
    data["geometry"] = data.geometry.simplify(0.02, preserve_topology=True)

    # Extra columns shown in the hover box.
    hover = {
        "region_name": True,
        "country": True,
        "population": ":,.0f",
        column: ":.3f" if data[column].max() <= 1 else ":,.1f",
    }

    figure = px.choropleth(
        data,
        geojson=data.__geo_interface__,
        locations="region_id",
        featureidkey="properties.region_id",
        color=column,
        hover_name="region_name",
        hover_data=hover,
        color_continuous_scale=colorscale,
        labels={column: label},
        title=title,
    )
    figure.update_geos(fitbounds="locations", visible=False)
    figure.update_layout(margin={"r": 0, "t": 50, "l": 0, "b": 0},
                         coloraxis_colorbar={"title": label})
    figure.write_html(path, include_plotlyjs="cdn", full_html=True)


def run() -> list[Path]:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])
    outputs = Path(cfg["paths"]["outputs"])

    master = pd.read_parquet(processed / "region_master.parquet")
    # `load_geo_table` repairs geometry columns, which can come back from
    # Parquet as raw WKB bytes rather than shapely objects.
    lisa = load_geo_table(processed / "lisa_clusters.parquet")
    regions = gpd.read_parquet(processed / "regions.parquet")

    # Attach geometry once; everything downstream receives a GeoDataFrame.
    gdf = regions[["region_id", "geometry"]].merge(master, on="region_id", how="left")
    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:4326")

    log("export: static maps")
    map_files = maps.plot_all(gdf, lisa, outputs / "maps")

    log("export: statistical figures")
    tables = {
        "lorenz": pd.read_parquet(processed / "desc_lorenz.parquet"),
        "coefficients": pd.read_parquet(processed / "regression_coefficients.parquet"),
        "slopes": pd.read_parquet(processed / "country_slopes.parquet"),
        "stability": pd.read_parquet(processed / "rank_stability.parquet"),
    }
    figure_files = charts.plot_all(master, tables, outputs / "figures")

    log("export: interactive maps")
    web_dir = outputs / "maps"
    web = []
    specs = [
        ("hazard_equal", "Climate hazard index", "Hazard index (0-1)", "YlOrRd", "map_web_hazard.html"),
        ("person_days_heat", "Population exposure to extreme heat",
         "Person-days above 35 C", "Cividis", "map_web_exposure.html"),
        ("shdi", "Subnational Human Development Index", "SHDI", "Viridis", "map_web_shdi.html"),
        ("risk_equal", "Composite climate risk", "Risk index (0-1)", "Magma", "map_web_risk.html"),
    ]
    for column, title, label, scale, filename in specs:
        if column not in gdf.columns:
            continue
        path = web_dir / filename
        interactive_map(gdf, column, path, title, label, colorscale=scale)
        web.append(path)

    manifest = {
        "maps": [str(p.relative_to(outputs)) for p in map_files],
        "figures": [str(p.relative_to(outputs)) for p in figure_files],
        "interactive": [str(p.relative_to(outputs)) for p in web],
    }
    with open(outputs / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    log(f"export: {len(map_files)} maps, {len(figure_files)} figures, {len(web)} web maps")
    return map_files + figure_files + web


if __name__ == "__main__":
    run()
