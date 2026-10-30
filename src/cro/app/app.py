"""Interactive dashboard (Plotly Dash).

The page is a single, scrolling editorial spread rather than a set of hidden
tabs. Reading order:

01  overview      - the question and the headline numbers
02  the map       - one map per country, or one large map for one country
03  the ranking   - the ten most stressed regions in the current view
04  the relation  - hazard against development, with the selected region marked
05  one place     - the selected region, compared with its country
06  methods       - how the index is built and what it cannot say

Run it with:  cro app
Then open http://127.0.0.1:8050
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import ALL, Input, Output, State, ctx, dash, dcc, html
from dash.exceptions import PreventUpdate
from statsmodels.nonparametric.smoothers_lowess import lowess

from cro.app.queries import load_data
from cro.app.summary import register_report_routes
from cro.utils import log

# ---------------------------------------------------------------------------
# Data is loaded once when the app starts, not on every click.
# ---------------------------------------------------------------------------

DATA = load_data()

COUNTRY_CODES = ["FRA", "IND", "USA"]
COUNTRY_NAMES = {"FRA": "France", "IND": "India", "USA": "United States"}
COUNTRY_ADJECTIVES = {"FRA": "france", "IND": "india", "USA": "united states"}
COUNTRY_COLORS = {"FRA": "#1a1512", "IND": "#6a0c06", "USA": "#3f5c3a"}


def _map_rows(iso3: str) -> pd.DataFrame:
    """Rows that make sense on a country map.

    The United States data includes Alaska, Hawai'i, Puerto Rico, Guam and
    American Samoa. Plotting all of them zooms the map out to the whole
    Pacific, so the US panel shows the continental states only. Those places
    remain in the ranking and profile data.
    """
    rows = DATA[DATA["iso3"] == iso3]
    if iso3 == "USA":
        rows = rows[
            rows["centroid_lon"].between(-130, -66)
            & rows["centroid_lat"].between(23, 50)
        ]
    return rows


MAP_ROWS = {iso3: _map_rows(iso3) for iso3 in COUNTRY_CODES}
REGION_BY_ID = DATA.set_index("region_id")


def _polygon_parts(geometry):
    """Every polygon of a region, so islands are drawn separately."""
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    return [part for part in getattr(geometry, "geoms", []) if part.geom_type == "Polygon"]


def _project(lon, lat):
    """Web Mercator. Longitude and latitude become comparable x and y units."""
    x = np.radians(np.asarray(lon, dtype=float))
    lat = np.clip(np.asarray(lat, dtype=float), -85, 85)
    y = np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return x, y


def _prepare_map_parts(iso3: str):
    """Project every region outline once, when the app starts.

    Coastlines break into hundreds of tiny islets (Bretagne alone has 975).
    At country scale those are invisible, so we keep polygons larger than
    0.02 square degrees (roughly 200 km2) and always keep the largest piece
    of a region, even when the whole region is a small island.
    """
    parts = []
    for _, row in MAP_ROWS[iso3].iterrows():
        polygons = _polygon_parts(row["geometry"])
        if not polygons:
            continue
        keep = [polygon for polygon in polygons if polygon.area >= 0.02]
        if not keep:
            keep = [max(polygons, key=lambda polygon: polygon.area)]

        for polygon in keep:
            coords = np.asarray(polygon.exterior.coords, dtype=float)
            if len(coords) < 4:
                continue
            x, y = _project(coords[:, 0], coords[:, 1])
            parts.append({"region_id": str(row["region_id"]), "x": x, "y": y})
    return parts


def _projected_bounds(iso3: str):
    """Axis ranges with a small margin around the country."""
    lon0, lat0, lon1, lat1 = MAP_ROWS[iso3].total_bounds
    x0, x1 = np.radians([lon0, lon1])
    y0, y1 = _project([0, 0], [lat0, lat1])[1]
    pad_x = max((x1 - x0) * 0.035, 0.004)
    pad_y = max((y1 - y0) * 0.035, 0.004)
    return (x0 - pad_x, x1 + pad_x), (y0 - pad_y, y1 + pad_y)


MAP_PARTS = {iso3: _prepare_map_parts(iso3) for iso3 in COUNTRY_CODES}
MAP_RANGES = {iso3: _projected_bounds(iso3) for iso3 in COUNTRY_CODES}


# ---------------------------------------------------------------------------
# Colours and measures
# ---------------------------------------------------------------------------

# A warm scale that reads from pale sage (low) to deep maroon (high).
WARM_COLORS = ["#e9eddc", "#d7d3ab", "#cbb478", "#be8a45", "#98421f", "#6a0c06"]
COOL_COLORS = list(reversed(WARM_COLORS))

INK = "#6a0c06"
DARK = "#1a1512"
PAPER = "#b2c7ab"

FONT = {"family": "Space Grotesk, Segoe UI, Arial, sans-serif", "color": INK, "size": 11}
HOVER = {
    "bgcolor": DARK,
    "bordercolor": DARK,
    "font": {"family": "Space Grotesk, Segoe UI, Arial, sans-serif", "color": "#e9eddc", "size": 12},
}

INDICATORS = {
    "risk_equal": {
        "label": "composite risk",
        "axis": "risk index",
        "fmt": "{:.3f}",
        "colors": WARM_COLORS,
        "low": "less risk",
        "high": "more risk",
        "rank_title": "the highest composite risk",
        "top_label": "Highest composite risk",
        "ascending": False,
    },
    "hazard_equal": {
        "label": "climate hazard",
        "axis": "hazard index",
        "fmt": "{:.3f}",
        "colors": WARM_COLORS,
        "low": "lower hazard",
        "high": "higher hazard",
        "rank_title": "the highest climate hazard",
        "top_label": "Highest climate hazard",
        "ascending": False,
    },
    "hd35_area": {
        "label": "heat days above 35 C",
        "axis": "days per year",
        "fmt": "{:,.1f}",
        "colors": WARM_COLORS,
        "low": "fewer hot days",
        "high": "more hot days",
        "rank_title": "the most days above 35 C",
        "top_label": "Most days above 35 C",
        "ascending": False,
    },
    "person_days_heat": {
        "label": "exposure to extreme heat",
        "axis": "person-days of heat",
        "fmt": "{:,.0f}",
        "colors": WARM_COLORS,
        "low": "lower exposure",
        "high": "higher exposure",
        "rank_title": "the largest heat exposure",
        "top_label": "Largest heat exposure",
        "ascending": False,
        "log": True,
    },
    "vulnerability": {
        "label": "vulnerability",
        "axis": "vulnerability index",
        "fmt": "{:.2f}",
        "colors": WARM_COLORS,
        "low": "less vulnerable",
        "high": "more vulnerable",
        "rank_title": "the highest vulnerability",
        "top_label": "Highest vulnerability",
        "ascending": False,
    },
    "shdi": {
        "label": "human development (SHDI)",
        "axis": "SHDI",
        "fmt": "{:.3f}",
        "colors": COOL_COLORS,
        "low": "lower SHDI",
        "high": "higher SHDI",
        "rank_title": "the lowest human development",
        "top_label": "Lowest SHDI",
        "ascending": True,
    },
}

MEASURE_CHOICES = [
    ("risk_equal", "risk"),
    ("hazard_equal", "hazard"),
    ("hd35_area", "heat days"),
    ("person_days_heat", "exposure"),
    ("vulnerability", "vulnerability"),
    ("shdi", "SHDI"),
]

COUNTRY_CHOICES = [
    ("all", "all"),
    ("FRA", "france"),
    ("IND", "india"),
    ("USA", "usa"),
]

# Headline numbers, computed once from the data rather than typed by hand.
TOTAL_POPULATION = DATA["population"].sum() / 1e9
N_REGIONS = len(DATA)
N_COUNTRIES = DATA["iso3"].nunique()
N_WITH_SHDI = int(DATA["shdi"].notna().sum())
N_RANKED = int(DATA["risk_equal"].notna().sum())
MEDIAN_RISK = float(DATA["risk_equal"].median())
RHO = float(
    DATA[["hazard_equal", "shdi"]].dropna().corr(method="spearman").iloc[0, 1]
)
RHO_TEXT = f"{RHO:.2f}".replace("-", "\u2212")
TOP_REGION = DATA.sort_values("risk_equal", ascending=False).iloc[0]["region_id"]


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def compact(value) -> str:
    """Turn 1,803,100,000 into 1.80bn for small spaces."""
    if pd.isna(value):
        return "n/a"
    value = float(value)
    if value >= 1e9:
        return f"{value / 1e9:.2f}bn"
    if value >= 1e6:
        return f"{value / 1e6:.1f}m"
    if value >= 1e3:
        return f"{value / 1e3:.1f}k"
    return f"{value:,.0f}"


def fmt_value(indicator: str, value) -> str:
    """Format one value in the units of the selected measure."""
    if pd.isna(value):
        return "n/a"
    if indicator == "person_days_heat":
        return compact(value)
    return INDICATORS[indicator]["fmt"].format(float(value))


def plot_values(indicator: str, values: pd.Series) -> pd.Series:
    """Values as plotted. Exposure spans many orders of magnitude."""
    values = values.astype(float)
    if INDICATORS[indicator].get("log"):
        return np.log10(values.clip(lower=1))
    return values


def visible_rows(view: str) -> pd.DataFrame:
    """The regions currently on screen."""
    if view in (None, "all"):
        return DATA
    return DATA[DATA["iso3"] == view]


def measure_bounds(indicator: str, view: str):
    """Colour-scale limits for the current view.

    Returns the limits used on the plot (log units for exposure) and the
    limits in the original units (for the legend labels).
    """
    values = visible_rows(view)[indicator].astype(float).dropna()
    if values.empty:
        return (0.0, 1.0), (0.0, 1.0)

    raw_low, raw_high = float(values.min()), float(values.max())
    if INDICATORS[indicator].get("log"):
        plot_low = float(np.log10(max(raw_low, 1)))
        plot_high = float(np.log10(max(raw_high, 1)))
    else:
        plot_low, plot_high = raw_low, raw_high

    if plot_high <= plot_low:
        plot_high = plot_low + 1e-6
    return (plot_low, plot_high), (raw_low, raw_high)


def blend(colors: list[str], t: float) -> str:
    """Pick a colour between the stops of a scale, for 0 <= t <= 1."""
    t = float(min(max(t, 0.0), 1.0))
    if len(colors) == 1:
        return colors[0]

    position = t * (len(colors) - 1)
    left = int(np.floor(position))
    right = min(left + 1, len(colors) - 1)
    fraction = position - left

    def rgb(color: str):
        color = color.lstrip("#")
        return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))

    a, b = rgb(colors[left]), rgb(colors[right])
    mixed = [round(a[i] + (b[i] - a[i]) * fraction) for i in range(3)]
    return f"rgb({mixed[0]},{mixed[1]},{mixed[2]})"



def percentile(values: pd.Series, value) -> float | None:
    """Where a value sits in a distribution, from 0 to 100."""
    if pd.isna(value):
        return None
    clean = values.dropna()
    if clean.empty:
        return None
    return float((clean <= value).mean() * 100)


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------

def empty_figure(message: str) -> go.Figure:
    """A quiet placeholder instead of a blank white box."""
    figure = go.Figure()
    figure.update_layout(
        height=260,
        margin={"l": 8, "r": 8, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=FONT,
        xaxis={"visible": False},
        yaxis={"visible": False},
        annotations=[{
            "text": message,
            "showarrow": False,
            "font": {"size": 12, "color": INK},
        }],
    )
    return figure


def build_country_map(indicator: str, iso3: str, bounds: tuple, height: int = 300) -> go.Figure:
    """A country map drawn as projected polygons.

    Plotly's Choropleth trace draws a background rectangle around each
    GeoJSON feature in this version, which hides the map. Drawing the
    projected outlines ourselves avoids that bug and keeps the basemap-free
    editorial look.
    """
    spec = INDICATORS[indicator]
    low, high = bounds
    span = max(high - low, 1e-9)
    traces = []

    for part in MAP_PARTS[iso3]:
        row = REGION_BY_ID.loc[part["region_id"]]
        raw = row[indicator]
        if pd.isna(raw):
            fill = "#cfd8c6"
            value_text = "n/a"
        else:
            plotted = float(np.log10(max(raw, 1))) if spec.get("log") else float(raw)
            fill = blend(spec["colors"], (plotted - low) / span)
            value_text = fmt_value(indicator, raw)

        hover = (
            f"<b>{row['region_name']}</b> \u00b7 {row['country']}<br>"
            f"Population {compact(row['population'])}<br>"
            f"Hazard {fmt_value('hazard_equal', row['hazard_equal'])} \u00b7 "
            f"SHDI {fmt_value('shdi', row['shdi'])}<br>"
            f"Risk {fmt_value('risk_equal', row['risk_equal'])}<br>"
            f"{spec['label']}: {value_text}"
        )

        point_data = np.tile(
            np.array([part["region_id"], hover, value_text], dtype=object),
            (len(part["x"]), 1),
        )

        traces.append(go.Scatter(
            x=part["x"],
            y=part["y"],
            mode="lines",
            fill="toself",
            fillcolor=fill,
            line={"color": "rgba(233,237,220,0.9)", "width": 0.55},
            hoveron="fills",
            hoverinfo="text",
            text=[hover] * len(part["x"]),
            customdata=point_data,
            name=str(row["region_name"]),
            showlegend=False,
        ))

    x_range, y_range = MAP_RANGES[iso3]
    figure = go.Figure(traces)
    figure.update_xaxes(
        visible=False,
        range=list(x_range),
        fixedrange=True,
        constrain="domain",
    )
    figure.update_yaxes(
        visible=False,
        range=list(y_range),
        fixedrange=True,
        scaleanchor="x",
        scaleratio=1,
        constrain="domain",
    )
    figure.update_layout(
        height=height,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=FONT,
        hoverlabel=HOVER,
        hovermode="closest",
        dragmode=False,
    )
    return figure


def build_legend(indicator: str, view: str):
    """HTML legend so the colour scale is readable without Plotly toolbars."""
    spec = INDICATORS[indicator]
    _, (raw_low, raw_high) = measure_bounds(indicator, view)

    if view == "all":
        scope = "shared across the three maps"
    else:
        scope = f"scaled to {COUNTRY_NAMES.get(view, view).lower()} only"

    return [
        html.Div([
            html.Span(f"colour = {spec['label']}", className="legend-title"),
            html.Span(scope, className="micro"),
        ], className="legend-head"),
        html.Div(
            className="legend-bar",
            style={"background": "linear-gradient(90deg," + ",".join(spec["colors"]) + ")"},
        ),
        html.Div([
            html.Span(f"{fmt_value(indicator, raw_low)} \u00b7 {spec['low']}"),
            html.Span(f"{fmt_value(indicator, raw_high)} \u00b7 {spec['high']}"),
        ], className="legend-ticks"),
    ]


def build_map_note(indicator: str, view: str):
    """One sentence that explains the current view, plus honest caveats."""
    spec = INDICATORS[indicator]
    rows = visible_rows(view).dropna(subset=[indicator])
    top = rows.sort_values(indicator, ascending=spec["ascending"]).iloc[0]

    parts = [
        html.B(f"{spec['top_label']}: {top['region_name']} ({fmt_value(indicator, top[indicator])}). "),
        "Click any region to open its profile. ",
    ]
    if view == "all":
        parts.append(
            "The colour scale is shared by all three maps, so shades compare across "
            "countries. India sets the top of the scale, which is why France and the "
            "United States look pale here; choose a country to rescale it. "
        )
    else:
        parts.append("The colour scale is fitted to this country, so it shows internal differences. ")
    if spec.get("log"):
        parts.append("Exposure is coloured on a log scale. ")
    if view in ("all", "USA"):
        parts.append(
            "The US panel shows the continental states; Alaska, Hawai\u02bbi and the "
            "territories remain in the ranking and profile data."
        )
    return parts


def build_scatter(selected_region: str | None, view: str) -> go.Figure:
    """Hazard against SHDI, one colour per country, selected region ringed."""
    data = visible_rows(view).dropna(subset=["hazard_equal", "shdi"]).copy()
    if data.empty:
        return empty_figure("No development data for this view.")

    figure = go.Figure()

    for iso3 in COUNTRY_CODES:
        group = data[data["iso3"] == iso3]
        if group.empty:
            continue
        figure.add_trace(go.Scatter(
            x=group["hazard_equal"],
            y=group["shdi"],
            mode="markers",
            name=COUNTRY_NAMES[iso3],
            marker={
                "size": 8,
                "color": COUNTRY_COLORS[iso3],
                "opacity": 0.82,
                "line": {"width": 0.6, "color": "#e9eddc"},
            },
            customdata=np.stack([
                group["region_name"].astype(str),
                group["risk_equal"].map(lambda v: "n/a" if pd.isna(v) else f"{v:.3f}"),
                group["population"].map(compact),
            ], axis=-1),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Hazard %{x:.3f}<br>"
                "SHDI %{y:.3f}<br>"
                "Risk %{customdata[1]} \u00b7 population %{customdata[2]}"
                "<extra></extra>"
            ),
        ))

    # Smooth trend line through all visible regions.
    if len(data) > 8:
        smooth = lowess(data["shdi"], data["hazard_equal"], frac=0.7)
        figure.add_trace(go.Scatter(
            x=smooth[:, 0],
            y=smooth[:, 1],
            mode="lines",
            name="trend (LOWESS)",
            line={"color": DARK, "width": 1.6},
            hoverinfo="skip",
        ))

    # Study medians as thin dashed guides.
    figure.add_vline(
        x=float(data["hazard_equal"].median()),
        line={"color": "rgba(106,12,6,0.35)", "width": 1, "dash": "dot"},
    )
    figure.add_hline(
        y=float(data["shdi"].median()),
        line={"color": "rgba(106,12,6,0.35)", "width": 1, "dash": "dot"},
    )

    # The selected region gets an open ring and a small label.
    if selected_region:
        row = DATA[DATA["region_id"] == selected_region]
        if not row.empty and pd.notna(row.iloc[0]["shdi"]):
            row = row.iloc[0]
            figure.add_trace(go.Scatter(
                x=[row["hazard_equal"]],
                y=[row["shdi"]],
                mode="markers",
                marker={
                    "size": 19,
                    "color": "rgba(0,0,0,0)",
                    "line": {"width": 2.2, "color": DARK},
                },
                name="selected",
                hoverinfo="skip",
                showlegend=False,
            ))
            figure.add_annotation(
                x=row["hazard_equal"],
                y=row["shdi"],
                text=row["region_name"],
                showarrow=True,
                arrowhead=0,
                arrowwidth=1,
                arrowcolor=DARK,
                ax=34,
                ay=-30,
                font={"size": 10, "color": DARK},
                bgcolor="rgba(178,199,171,0.9)",
                borderpad=3,
            )

    figure.update_layout(
        height=500,
        margin={"l": 10, "r": 14, "t": 42, "b": 40},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=FONT,
        hoverlabel=HOVER,
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.02,
            "yanchor": "bottom",
            "font": {"size": 10},
            "bgcolor": "rgba(0,0,0,0)",
        },
    )
    figure.update_xaxes(
        title={"text": "Climate hazard index (0-1)", "font": {"size": 10}},
        range=[0, 1],
        gridcolor="rgba(106,12,6,0.14)",
        zeroline=False,
        linecolor="rgba(106,12,6,0.35)",
        ticks="outside",
        ticklen=4,
        tickfont={"size": 9},
    )
    figure.update_yaxes(
        title={"text": "Subnational HDI (SHDI)", "font": {"size": 10}},
        gridcolor="rgba(106,12,6,0.14)",
        zeroline=False,
        linecolor="rgba(106,12,6,0.35)",
        ticks="outside",
        ticklen=4,
        tickfont={"size": 9},
    )
    return figure


def build_profile_chart(region_id: str | None) -> go.Figure:
    """Percentile position of one region, with its country median marked.

    Raw values are on very different scales (heat days vs an index from 0 to
    1), so comparing them on one axis is meaningless. Percentiles put them on
    a common 0-100 scale; the hover box still shows the real values.
    """
    if not region_id:
        return empty_figure("Choose a region to see its profile.")

    row = DATA[DATA["region_id"] == region_id]
    if row.empty:
        return empty_figure("Region not found.")
    row = row.iloc[0]
    country = DATA[DATA["iso3"] == row["iso3"]]

    metrics = [
        ("Risk", "risk_equal"),
        ("Vulnerability", "vulnerability"),
        ("Hazard", "hazard_equal"),
        ("Exposure", "person_days_heat"),
        ("Heat days", "hd35_area"),
        ("SHDI", "shdi"),
    ]

    labels, position, hover = [], [], []
    country_position, country_hover = [], []

    for label, column in metrics:
        values = DATA[column]
        pct = percentile(values, row[column])
        position.append(0 if pct is None else pct)
        hover.append([
            fmt_value(column, row[column]) if column != "person_days_heat" else compact(row[column]),
            "n/a" if pct is None else f"{pct:.0f}th percentile",
        ])

        median = country[column].median()
        cpct = percentile(values, median)
        country_position.append(0 if cpct is None else cpct)
        country_hover.append([
            "n/a" if pd.isna(median) else (
                compact(median) if column == "person_days_heat" else INDICATORS[column]["fmt"].format(median)
            ),
            "n/a" if cpct is None else f"{cpct:.0f}th percentile",
        ])
        labels.append(label)

    figure = go.Figure()
    figure.add_trace(go.Bar(
        x=position,
        y=labels,
        orientation="h",
        name="this region",
        marker={"color": INK, "line": {"width": 0}},
        width=0.5,
        customdata=hover,
        hovertemplate=(
            "<b>%{y}</b><br>%{customdata[0]}<br>%{customdata[1]}"
            "<extra></extra>"
        ),
    ))
    figure.add_trace(go.Scatter(
        x=country_position,
        y=labels,
        mode="markers",
        name="country median",
        marker={
            "symbol": "diamond",
            "size": 9,
            "color": DARK,
            "line": {"width": 1, "color": "#e9eddc"},
        },
        customdata=country_hover,
        hovertemplate=(
            "<b>%{y}</b> \u00b7 country median<br>%{customdata[0]}<br>"
            "%{customdata[1]}<extra></extra>"
        ),
    ))

    figure.add_vline(
        x=50,
        line={"color": "rgba(26,21,18,0.35)", "width": 1, "dash": "dot"},
    )

    figure.update_layout(
        height=340,
        margin={"l": 92, "r": 16, "t": 30, "b": 32},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=FONT,
        hoverlabel=HOVER,
        barmode="overlay",
        legend={
            "orientation": "h",
            "x": 0,
            "y": 1.12,
            "font": {"size": 9},
            "bgcolor": "rgba(0,0,0,0)",
        },
    )
    figure.update_xaxes(
        title={"text": "percentile among regions with data", "font": {"size": 10}},
        range=[0, 100],
        gridcolor="rgba(106,12,6,0.14)",
        zeroline=False,
        linecolor="rgba(106,12,6,0.35)",
        tickfont={"size": 9},
    )
    figure.update_yaxes(
        autorange="reversed",
        gridcolor="rgba(106,12,6,0.08)",
        linecolor="rgba(106,12,6,0.35)",
        tickfont={"size": 10},
    )
    return figure


# ---------------------------------------------------------------------------
# HTML builders: region detail, ranking, ticker and methods
# ---------------------------------------------------------------------------

def detail_rows(region_id: str | None):
    """The region card shown in section 05."""
    if not region_id:
        return [html.P("Choose a region above, or click one on the map.", className="empty")]

    row = DATA[DATA["region_id"] == region_id]
    if row.empty:
        return [html.P("Region not found.", className="empty")]
    row = row.iloc[0]

    rank = row["risk_rank"]
    rank_text = "n/a" if pd.isna(rank) else f"{int(rank):02d}"

    cells = [
        ("risk rank", rank_text, f" of {N_RANKED}"),
        ("risk index", fmt_value("risk_equal", row["risk_equal"]), ""),
        ("hazard index", fmt_value("hazard_equal", row["hazard_equal"]), ""),
        ("heat days / year", fmt_value("hd35_area", row["hd35_area"]), ""),
        ("population", compact(row["population"]), ""),
        ("SHDI", fmt_value("shdi", row["shdi"]), ""),
        ("vulnerability", fmt_value("vulnerability", row["vulnerability"]), ""),
        ("heat exposure", compact(row["person_days_heat"]), " person-days"),
    ]

    return [
        html.P(
            f"{COUNTRY_NAMES.get(row['iso3'], row['iso3'])} \u00b7 {row['iso3']}",
            className="profile-country",
        ),
        html.H3(str(row["region_name"]), className="profile-name"),
        html.Div([
            html.Div([
                html.Span(label, className="detail-label"),
                html.Span([
                    value,
                    html.Small(suffix) if suffix else "",
                ], className="detail-value"),
            ], className="detail")
            for label, value, suffix in cells
        ], className="detail-grid"),
    ]


def build_ranking(indicator: str, view: str):
    """Top ten regions for the current measure and view.

    Returns the row elements, the matching region ids (for click handling)
    and a heading that names the measure.
    """
    spec = INDICATORS[indicator]
    data = visible_rows(view).dropna(subset=[indicator])
    data = data.sort_values(indicator, ascending=spec["ascending"]).head(10)

    # Bar length is the measure relative to the strongest region in this
    # list, so the top row always fills the bar and the rest show the gap.
    values = data[indicator].astype(float)
    if spec["ascending"]:
        spread = max(float(values.max() - values.min()), 1e-9)
        concern = (float(values.max()) - values) / spread * 100
    else:
        concern = values / max(float(values.max()), 1e-9) * 100

    rows, ids = [], []
    for number, (_, row) in enumerate(data.iterrows(), start=1):
        width = float(concern.loc[row.name])
        if pd.isna(width):
            width = 0
        rows.append(html.Button(
            [
                html.Span(f"{number:02d}", className="rank-n"),
                html.Span([
                    html.Span(str(row["region_name"]), className="rank-name"),
                    html.Span(
                        f"{row['iso3']} \u00b7 {COUNTRY_NAMES.get(row['iso3'], row['iso3'])}",
                        className="rank-country",
                    ),
                ], className="rank-who"),
                html.Span(
                    html.Span(style={"width": f"{max(2, min(100, width)):.1f}%"}),
                    className="rank-bar",
                ),
                html.Span(fmt_value(indicator, row[indicator]), className="rank-value"),
            ],
            id={"type": "rank-row", "index": number - 1},
            n_clicks=0,
            className="rank-row",
            title=f"Show {row['region_name']} in the profile",
        ))
        ids.append(str(row["region_id"]))

    return rows, ids, spec["rank_title"]


def ticker_segment():
    """One copy of the number strip in the fixed header."""
    items = [
        ("105", "admin-1 regions"),
        ("3", "countries"),
        (f"{TOTAL_POPULATION:.2f}bn", "people covered"),
        (f"{MEDIAN_RISK:.3f}", "median risk"),
        (RHO_TEXT, "hazard-SHDI rank correlation"),
        ("bih\u0101r", "highest risk region"),
    ]
    # Doubling the items makes the strip wider than most screens.
    doubled = items * 2
    return html.Div(
        [html.Span([html.B(value), f" {label}"]) for value, label in doubled],
        className="ticker-seg",
    )


METHODS = [
    (
        "01 / hazard",
        "Six climate measures from NASA POWER daily data (1991-2023): days above "
        "35 C, tropical nights, the longest dry spell, water balance, the heaviest "
        "one-day rainfall and very wet days. Each is converted to a percentile, "
        "combined into heat, dry and wet sub-indices, then averaged.",
    ),
    (
        "02 / exposure",
        "GHS-POP 2020 population at 30 arc-seconds. Each person is assigned to the "
        "nearest climate sample point, so person-days of extreme heat = population "
        "x heat days. This is why a hot but empty region does not rank like a hot "
        "and crowded one.",
    ),
    (
        "03 / vulnerability",
        "One minus the percentile rank of the subnational Human Development Index "
        "(Global Data Lab). Regions without an SHDI keep their hazard and exposure "
        "scores but are left out of the development models.",
    ),
    (
        "04 / risk",
        "Composite risk = hazard x exposure x vulnerability, following the IPCC "
        "framing. An additive version and a PCA-weighted version are kept as "
        "robustness checks; the regional ordering barely moves between them.",
    ),
    (
        "05 / statistics",
        "Mann-Whitney tests, Cliff's delta and Spearman correlation for the "
        "development relationship; country fixed effects for the regression; "
        "Moran's I and LISA for spatial clustering. Full tables are in the report.",
    ),
    (
        "06 / scope",
        "Pilot of 105 admin-1 regions in France, India and the United States. The "
        "pipeline is written to scale to roughly 3,700 regions worldwide without "
        "changing the index definition.",
    ),
]


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def layout() -> html.Div:
    initial_bounds, _ = measure_bounds("risk_equal", "all")
    initial_rows, initial_ids, initial_heading = build_ranking("risk_equal", "all")
    region_options = [
        {
            "label": f"{row.region_name} \u00b7 {row.iso3}",
            "value": row.region_id,
        }
        for row in DATA.sort_values(["iso3", "region_name"]).itertuples()
    ]

    map_panels = []
    for iso3 in COUNTRY_CODES:
        map_panels.append(html.Div(
            [
                html.Div([
                    html.H3(COUNTRY_ADJECTIVES[iso3], className="map-country"),
                    html.Span(
                        f"{len(MAP_ROWS[iso3])} regions",
                        className="map-meta",
                    ),
                ], className="map-panel-head"),
                dcc.Graph(
                    id=f"map-{iso3}",
                    figure=build_country_map("risk_equal", iso3, initial_bounds, 320),
                    config={"displayModeBar": False, "responsive": True},
                ),
            ],
            id=f"panel-{iso3}",
            className="map-panel",
        ))

    return html.Div([
        # Hairline layout grid behind the page.
        html.Div(
            [html.Span() for _ in range(12)],
            className="grid-overlay",
            **{"aria-hidden": "true"},
        ),

        # Fixed top bar: wordmark, number ticker, section links.
        html.Header([
            html.A("cro.", href="#top", className="brand"),
            html.Div(
                html.Div([ticker_segment(), ticker_segment()], className="ticker-track"),
                className="ticker",
            ),
            html.Nav([
                html.A("map", href="#map"),
                html.A("ranking", href="#ranking"),
                html.A("relationship", href="#relationship"),
                html.A("profile", href="#profile"),
                html.A("methods", href="#methods"),
                html.A("summary", href="/summary"),
            ], className="topnav"),
        ], className="topbar"),

        html.Main([
            # 01 - overview -------------------------------------------------
            html.Section([
                html.Div([
                    html.P("climate risk & human development observatory", className="eyebrow"),
                    html.P("pilot \u00b7 france / india / united states", className="eyebrow"),
                ], className="eyebrow-row"),

                html.H1([
                    "where climate stress",
                    html.Span("meets low development.", className="light"),
                ]),

                html.Div([
                    html.Div([
                        html.P([
                            "A regional observatory built from NASA climate records, "
                            "population grids and subnational development data. Every "
                            "region is scored for ", html.B("hazard"), ", ",
                            html.B("exposure"), " and ", html.B("vulnerability"),
                            ", then set against its level of human development. "
                            "Click a map to inspect a place.",
                        ], className="lede"),
                        html.A(
                            ["read the two-minute summary ", html.Span("\u2192")],
                            href="/summary",
                            className="hero-link",
                        ),
                    ], className="hero-copy"),
                    html.Div([
                        html.Div([
                            html.Span(f"{N_REGIONS}", className="stat-value"),
                            html.Span("admin-1 regions", className="stat-label"),
                        ], className="stat"),
                        html.Div([
                            html.Span(f"{N_COUNTRIES}", className="stat-value"),
                            html.Span("countries in the pilot", className="stat-label"),
                        ], className="stat"),
                        html.Div([
                            html.Span(f"{TOTAL_POPULATION:.2f}bn", className="stat-value"),
                            html.Span("people covered", className="stat-label"),
                        ], className="stat"),
                        html.Div([
                            html.Span(RHO_TEXT, className="stat-value"),
                            html.Span("hazard-SHDI rank correlation", className="stat-label"),
                        ], className="stat"),
                    ], className="stats"),
                ], className="hero-bottom"),
            ], className="hero", id="top"),

            # Controls ------------------------------------------------------
            html.Div([
                html.Div([
                    html.Div([
                        html.Span("view by country", className="control-label"),
                        dcc.RadioItems(
                            id="country-view",
                            options=[{"label": label, "value": value}
                                     for value, label in COUNTRY_CHOICES],
                            value="all",
                            inline=True,
                            className="chips",
                            labelClassName="chip",
                            inputClassName="chip-input",
                        ),
                    ], className="control-block"),
                    html.Div([
                        html.Span("measure shown on the map", className="control-label"),
                        dcc.RadioItems(
                            id="measure",
                            options=[{"label": label, "value": value}
                                     for value, label in MEASURE_CHOICES],
                            value="risk_equal",
                            inline=True,
                            className="chips",
                            labelClassName="chip",
                            inputClassName="chip-input",
                        ),
                    ], className="control-block"),
                    html.Div([
                        html.Span("find a region", className="control-label"),
                        dcc.Dropdown(
                            id="region-select",
                            options=region_options,
                            value=TOP_REGION,
                            clearable=False,
                            searchable=True,
                            placeholder="search a region",
                            className="region-dropdown",
                        ),
                    ], className="control-block control-region"),
                ], className="controls-grid"),
            ], className="controls", id="controls"),

            # 02 - map ------------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("02", className="section-num"),
                    html.H2("the map.", className="section-title"),
                    html.P(
                        "Three countries, one shared colour scale when they are shown "
                        "together. Pick a country above to enlarge its map and see "
                        "internal differences.",
                        className="section-desc",
                    ),
                ], className="section-head"),
                html.Div(map_panels, className="map-grid"),
                html.Div(build_legend("risk_equal", "all"), id="map-legend", className="map-legend"),
                html.P(build_map_note("risk_equal", "all"), id="map-note", className="map-note"),
            ], className="section", id="map"),

            # 03 - ranking --------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("03", className="section-num"),
                    html.H2("the ranking.", className="section-title"),
                    html.P([
                        "The ten regions with ",
                        html.Span(initial_heading, id="rank-heading"),
                        ". Click a row to load it in the profile at the bottom of the page.",
                    ], className="section-desc"),
                ], className="section-head"),
                html.Div(initial_rows, id="rank-list", className="rank-list"),
                dcc.Store(id="rank-store", data=initial_ids),
            ], className="section", id="ranking"),

            # 04 - relationship ---------------------------------------------
            html.Section([
                html.Div([
                    html.Span("04", className="section-num"),
                    html.H2("the relationship.", className="section-title"),
                    html.P(
                        "Hazard against development. The dashed lines mark the study "
                        "medians; the ring marks the region you selected.",
                        className="section-desc",
                    ),
                ], className="section-head"),
                html.Div([
                    html.Div([
                        dcc.Graph(
                            id="scatter-graph",
                            figure=build_scatter(TOP_REGION, "all"),
                            config={"displayModeBar": False, "responsive": True},
                        ),
                        html.P(
                            "Each dot is one admin-1 region. High SHDI sits high on the "
                            "y-axis; high hazard sits to the right. The pattern runs "
                            "downward: more hazard, less development.",
                            className="chart-caption",
                        ),
                    ], className="chart-panel"),
                    html.Div([
                        html.Span(RHO_TEXT, className="finding-big"),
                        html.Span(
                            "Spearman rank correlation between climate hazard and SHDI, "
                            "across the 99 regions with development data.",
                            className="finding-label",
                        ),
                        html.Ul([
                            html.Li([
                                html.B("medians"),
                                html.Span(
                                    "SHDI 0.786 in high-hazard regions vs 0.936 in "
                                    "low-hazard regions (Mann-Whitney p = 1.4e-06)."
                                ),
                            ]),
                            html.Li([
                                html.B("within"),
                                html.Span(
                                    "A one-SD rise in hazard goes with -0.21 SD of "
                                    "SHDI inside countries (95% CI -0.32 to -0.11)."
                                ),
                            ]),
                            html.Li([
                                html.B("by country"),
                                html.Span(
                                    "Slope -0.22 in India, -0.14 in the USA and +0.01 "
                                    "in France, where hazard range is narrow."
                                ),
                            ]),
                            html.Li([
                                html.B("concentration"),
                                html.Span(
                                    "The top 10% most hazardous regions hold 1.38x "
                                    "their population share of person-days of heat."
                                ),
                            ]),
                        ], className="finding-list"),
                    ], className="finding"),
                ], className="split section-body"),
            ], className="section", id="relationship"),

            # 05 - profile --------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("05", className="section-num"),
                    html.H2("one place.", className="section-title"),
                    html.P(
                        "The chosen region in absolute numbers, and where it sits in "
                        "the distribution. The diamond is its country median.",
                        className="section-desc",
                    ),
                ], className="section-head"),
                html.Div([
                    html.Div(detail_rows(TOP_REGION), id="region-detail", className="profile-card"),
                    html.Div([
                        dcc.Graph(
                            id="profile-graph",
                            figure=build_profile_chart(TOP_REGION),
                            config={"displayModeBar": False, "responsive": True},
                        ),
                        html.P(
                            "Bars show percentile position among the pilot regions that "
                            "have data for that measure, from 0 (lowest) to 100 (highest). "
                            "The dotted line is the study median, the diamond is the "
                            "country median. Hover to read the raw values.",
                            className="chart-caption",
                        ),
                    ], className="chart-panel"),
                ], className="split section-body"),
            ], className="section", id="profile"),

            # 06 - methods --------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("06", className="section-num"),
                    html.H2("methods & data.", className="section-title"),
                    html.P(
                        "How the index is built, and the limits of what it can say. "
                        "The full statistical report is in the repository.",
                        className="section-desc",
                    ),
                ], className="section-head"),
                html.Div([
                    html.Div([
                        html.H3(heading),
                        html.P(text),
                    ], className="method")
                    for heading, text in METHODS
                ], className="methods-grid"),
                html.Div([
                    html.H3("Read this before quoting a number"),
                    html.P(
                        "These are associations, not causal effects. Climate, history, "
                        "institutions and geography are entangled, and this pilot "
                        "cannot separate them. Development data are missing for 6 of "
                        "the 105 regions, so development tests use 99. Boundaries are "
                        "ADM1 units, not lived neighbourhoods; a large region can hide "
                        "a hot city. Use the ranking as a screening tool, not a verdict."
                    ),
                ], className="caveat"),
                html.P(
                    "NASA POWER (MERRA-2) \u00b7 GHS-POP 2020 (JRC) \u00b7 geoBoundaries "
                    "ADM1 \u00b7 World Bank WDI \u00b7 Global Data Lab SHDI",
                    className="data-line",
                ),
            ], className="section", id="methods"),

            # Read further: the written summary and the full report. --------
            html.Div([
                html.Div([
                    html.Span("read further", className="next-kicker"),
                    html.H2("the written argument.", className="next-title"),
                ], className="next-head"),
                html.Div([
                    html.A([
                        html.Span("two-minute summary", className="next-link-title"),
                        html.Span("the question, four findings, limits", className="next-link-meta"),
                    ], href="/summary", className="next-link"),
                    html.A([
                        html.Span("full report \u2197", className="next-link-title"),
                        html.Span("html \u00b7 opens in this tab", className="next-link-meta"),
                    ], href="/report", className="next-link"),
                    html.A([
                        html.Span("report.pdf \u2193", className="next-link-title"),
                        html.Span("print layout", className="next-link-meta"),
                    ], href="/report.pdf", className="next-link"),
                ], className="next-links"),
            ], className="next-band"),
        ], className="shell"),

        html.Footer([
            html.Span("climate risk & human development observatory \u00b7 pilot edition"),
            html.Span("python \u00b7 postgis \u00b7 plotly"),
        ], className="footer shell"),
    ], className="page")


# ---------------------------------------------------------------------------
# App and callbacks
# ---------------------------------------------------------------------------

def create_app() -> dash.Dash:
    assets_folder = str(__import__("pathlib").Path(__file__).with_name("assets"))
    application = dash.Dash(
        __name__,
        assets_folder=assets_folder,
        title="Climate Risk Observatory",
        update_title=None,
    )
    application.layout = layout()

    # The written summary and the report files are plain Flask pages, not
    # Dash layouts: they never change, so they do not need callbacks.
    register_report_routes(application.server)

    @application.callback(
        Output("map-FRA", "figure"),
        Output("map-IND", "figure"),
        Output("map-USA", "figure"),
        Output("panel-FRA", "className"),
        Output("panel-IND", "className"),
        Output("panel-USA", "className"),
        Output("map-legend", "children"),
        Output("map-note", "children"),
        Output("rank-list", "children"),
        Output("rank-store", "data"),
        Output("rank-heading", "children"),
        Input("measure", "value"),
        Input("country-view", "value"),
    )
    def _update_view(indicator, view):
        indicator = indicator or "risk_equal"
        view = view or "all"

        bounds, _ = measure_bounds(indicator, view)
        height = 560 if view != "all" else 320

        figures = {
            iso3: build_country_map(indicator, iso3, bounds, height)
            for iso3 in COUNTRY_CODES
        }
        classes = {}
        for iso3 in COUNTRY_CODES:
            name = "map-panel"
            if view not in ("all", iso3):
                name += " is-hidden"
            if view == iso3:
                name += " map-panel-wide"
            classes[iso3] = name

        rows, ids, heading = build_ranking(indicator, view)
        return (
            figures["FRA"], figures["IND"], figures["USA"],
            classes["FRA"], classes["IND"], classes["USA"],
            build_legend(indicator, view),
            build_map_note(indicator, view),
            rows, ids, heading,
        )

    @application.callback(
        Output("region-select", "value"),
        Input("map-FRA", "clickData"),
        Input("map-IND", "clickData"),
        Input("map-USA", "clickData"),
        prevent_initial_call=True,
    )
    def _select_from_map(click_fra, click_ind, click_usa):
        for click in (click_fra, click_ind, click_usa):
            if click and click.get("points"):
                point = click["points"][0]
                region = point.get("location")
                if not region:
                    extra = point.get("customdata")
                    region = extra[0] if isinstance(extra, (list, tuple)) else extra
                if region:
                    return region
        raise PreventUpdate

    @application.callback(
        Output("region-select", "value", allow_duplicate=True),
        Input({"type": "rank-row", "index": ALL}, "n_clicks"),
        State("rank-store", "data"),
        prevent_initial_call=True,
    )
    def _select_from_ranking(clicks, region_ids):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or not region_ids:
            raise PreventUpdate
        if not ctx.triggered or not ctx.triggered[0]["value"]:
            raise PreventUpdate
        index = triggered.get("index")
        if index is None or index >= len(region_ids):
            raise PreventUpdate
        return region_ids[index]

    @application.callback(
        Output("region-select", "value", allow_duplicate=True),
        Input("country-view", "value"),
        State("region-select", "value"),
        prevent_initial_call=True,
    )
    def _follow_country(view, current):
        """When a country is chosen, show its highest-risk region."""
        if view in (None, "all"):
            raise PreventUpdate
        row = DATA[DATA["region_id"] == current]
        if not row.empty and row.iloc[0]["iso3"] == view:
            raise PreventUpdate
        top = (
            visible_rows(view)
            .dropna(subset=["risk_equal"])
            .sort_values("risk_equal", ascending=False)
            .iloc[0]
        )
        return top["region_id"]

    @application.callback(
        Output("region-detail", "children"),
        Input("region-select", "value"),
    )
    def _update_detail(region_id):
        return detail_rows(region_id)

    @application.callback(
        Output("scatter-graph", "figure"),
        Input("region-select", "value"),
        Input("country-view", "value"),
    )
    def _update_scatter(region_id, view):
        return build_scatter(region_id, view or "all")

    @application.callback(
        Output("profile-graph", "figure"),
        Input("region-select", "value"),
    )
    def _update_profile(region_id):
        return build_profile_chart(region_id)

    return application


def run_app() -> None:
    """Start the server on the port the host gives us.

    Locally that is 8050. Render, Railway and most container hosts set a
    PORT variable and expect the app to listen on 0.0.0.0, not just on
    localhost, so read both from the environment.
    """
    app = create_app()
    port = int(os.environ.get("PORT", "8050"))
    log(f"dashboard: running on http://127.0.0.1:{port} (bound to 0.0.0.0)")
    app.run(debug=False, host="0.0.0.0", port=port)


if __name__ == "__main__":
    run_app()
