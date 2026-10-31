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
from flask import request

from cro.app.i18n import COOKIE_NAME, LANGS
from cro.app.i18n import compact as compact_number
from cro.app.i18n import current_lang, normalize, num, t, tf
from cro.app.queries import load_data
from cro.app.summary import register_report_routes
from cro.utils import log

# ---------------------------------------------------------------------------
# Data is loaded once when the app starts, not on every click.
# ---------------------------------------------------------------------------

DATA = load_data()

COUNTRY_CODES = ["FRA", "IND", "USA"]
COUNTRY_COLORS = {"FRA": "#1a1512", "IND": "#6a0c06", "USA": "#3f5c3a"}
# "1.80bn" reads as one token; French wants a space before "Md".
BILLION_SUFFIX = {"en": "bn", "fr": "\u00a0Md"}


def _lang(lang: str | None = None) -> str:
    """Resolve the language for a builder: explicit, request, or English."""
    return normalize(lang) if lang else current_lang()


def country_name(iso3: str, lang: str | None = None) -> str:
    return t(f"country.name.{iso3}", _lang(lang)) if iso3 in COUNTRY_CODES else iso3


def country_adjective(iso3: str, lang: str | None = None) -> str:
    return t(f"country.{iso3}", _lang(lang)) if iso3 in COUNTRY_CODES else iso3.lower()



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

FONT = {"family": "Space Grotesk, Segoe UI, Arial, sans-serif", "color": INK, "size": 11}
HOVER = {
    "bgcolor": DARK,
    "bordercolor": DARK,
    "font": {"family": "Space Grotesk, Segoe UI, Arial, sans-serif", "color": "#e9eddc", "size": 12},
}

INDICATORS = {
    "risk_equal": {
        "key": "risk",
        "fmt": "{:.3f}",
        "colors": WARM_COLORS,
        "ascending": False,
    },
    "hazard_equal": {
        "key": "hazard",
        "fmt": "{:.3f}",
        "colors": WARM_COLORS,
        "ascending": False,
    },
    "hd35_area": {
        "key": "heat",
        "fmt": "{:,.1f}",
        "colors": WARM_COLORS,
        "ascending": False,
    },
    "population": {
        "key": "exposure",
        "fmt": "{:,.0f}",
        "colors": WARM_COLORS,
        "ascending": False,
        "log": True,
    },
    "vulnerability": {
        "key": "vulnerability",
        "fmt": "{:.2f}",
        "colors": WARM_COLORS,
        "ascending": False,
    },
    "shdi": {
        "key": "shdi",
        "fmt": "{:.3f}",
        "colors": COOL_COLORS,
        "ascending": True,
    },
}

MEASURE_CHOICES = [
    ("risk_equal", "risk"),
    ("hazard_equal", "hazard"),
    ("hd35_area", "heat"),
    ("population", "exposure"),
    ("vulnerability", "vulnerability"),
    ("shdi", "shdi"),
]

COUNTRY_CHOICES = [
    ("all", "all"),
    ("FRA", "FRA"),
    ("IND", "IND"),
    ("USA", "USA"),
]


# Headline numbers, computed once from the data rather than typed by hand.
TOTAL_POPULATION = DATA["population"].sum() / 1e9
N_REGIONS = len(DATA)
N_COUNTRIES = DATA["iso3"].nunique()
N_RANKED = int(DATA["risk_equal"].notna().sum())
MEDIAN_RISK = float(DATA["risk_equal"].median())
RHO = float(
    DATA[["hazard_equal", "shdi"]].dropna().corr(method="spearman").iloc[0, 1]
)
RHO_TEXT = f"{RHO:.2f}".replace("-", "\u2212")
TOP_REGION = DATA.sort_values("risk_equal", ascending=False).iloc[0]["region_id"]


def _load_results() -> dict:
    """Key results from the analysis tables (H1, H2, H3).

    The dashboard reads them from outputs/tables so the numbers on screen
    are always the ones in the report. If a table is missing, the values
    are empty and the text shows "n/a".
    """
    from cro.app.summary import TABLES_DIR as tables

    try:
        h1 = pd.read_csv(tables / "t05_hypothesis_tests.csv").set_index("group")
        models = pd.read_csv(tables / "t07_regression_coefficients.csv").set_index("model")
        stability = pd.read_csv(tables / "t06_rank_stability.csv")
    except (FileNotFoundError, KeyError) as error:
        log(f"dashboard: result tables not found ({error})")
        return {}
    within = models.loc["M2 country effects"]
    return {
        "median_high": h1.loc["ALL", "median_shdi_high_hazard"],
        "median_low": h1.loc["ALL", "median_shdi_low_hazard"],
        "p_value": h1.loc["ALL", "p_value"],
        "rho_ind": h1.loc["IND", "spearman_rho"],
        "rho_usa": h1.loc["USA", "spearman_rho"],
        "rho_fra": h1.loc["FRA", "spearman_rho"],
        "beta_all": models.loc["M1 all regions", "beta"],
        "beta": within["beta"],
        "beta_low": within["ci_low"],
        "beta_high": within["ci_high"],
        "min_rho": stability["spearman_rho"].min(),
        "min_top10": stability["same_in_top10"].min(),
    }


RESULTS = _load_results()


def _p_text(p_value: float, lang: str) -> str:
    """'p < 0.001' for very small values, else 'p = 0.012'."""
    text = "p < 0.001" if p_value < 0.001 else f"p = {p_value:.3f}"
    return text.replace(".", ",") if lang == "fr" else text


def result_text(key: str, lang: str) -> str:
    """A finding sentence with the numbers from the analysis tables."""
    if not RESULTS:
        return t("misc.na", lang)
    r = RESULTS
    return tf(
        key, lang,
        median_high=num(r["median_high"], 3, lang),
        median_low=num(r["median_low"], 3, lang),
        p_value=_p_text(r["p_value"], lang),
        rho_ind=num(r["rho_ind"], 2, lang),
        rho_usa=num(r["rho_usa"], 2, lang),
        rho_fra=num(r["rho_fra"], 2, lang),
        beta_all=num(r["beta_all"], 2, lang),
        beta=num(r["beta"], 2, lang),
        beta_low=num(r["beta_low"], 2, lang),
        beta_high=num(r["beta_high"], 2, lang),
        min_rho=num(r["min_rho"], 2, lang),
        min_top10=int(r["min_top10"]),
    )


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def compact(value, lang: str | None = None) -> str:
    """Turn 1,803,100,000 into 1.80bn for small spaces."""
    return compact_number(value, _lang(lang))


def fmt_value(indicator: str, value, lang: str | None = None) -> str:
    """Format one value in the units of the selected measure."""
    lang = _lang(lang)
    if pd.isna(value):
        return t("misc.na", lang)
    if indicator == "population":
        return compact(value, lang)
    text = INDICATORS[indicator]["fmt"].format(float(value))
    if lang == "fr":
        text = text.replace(",", "\u202f").replace(".", ",")
    return text



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


def build_country_map(
    indicator: str, iso3: str, bounds: tuple, height: int = 300,
    lang: str | None = None,
) -> go.Figure:
    """A country map drawn as projected polygons.

    Plotly's Choropleth trace draws a background rectangle around each
    GeoJSON feature in this version, which hides the map. Drawing the
    projected outlines ourselves avoids that bug and keeps the basemap-free
    editorial look.
    """
    lang = _lang(lang)
    spec = INDICATORS[indicator]
    low, high = bounds
    span = max(high - low, 1e-9)
    traces = []

    for part in MAP_PARTS[iso3]:
        row = REGION_BY_ID.loc[part["region_id"]]
        raw = row[indicator]
        if pd.isna(raw):
            fill = "#cfd8c6"
            value_text = t("misc.na", lang)
        else:
            plotted = float(np.log10(max(raw, 1))) if spec.get("log") else float(raw)
            fill = blend(spec["colors"], (plotted - low) / span)
            value_text = fmt_value(indicator, raw, lang)

        hover = (
            f"<b>{row['region_name']}</b> \u00b7 {country_name(row['iso3'], lang)}<br>"
            f"{t('hover.population', lang)} {compact(row['population'], lang)}<br>"
            f"{t('hover.hazard', lang)} {fmt_value('hazard_equal', row['hazard_equal'], lang)} \u00b7 "
            f"{t('hover.shdi', lang)} {fmt_value('shdi', row['shdi'], lang)}<br>"
            f"{t('hover.risk', lang)} {fmt_value('risk_equal', row['risk_equal'], lang)}<br>"
            f"{t('measure.' + spec['key'] + '.label', lang)}: {value_text}"
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


def build_legend(indicator: str, view: str, lang: str | None = None):
    """HTML legend so the colour scale is readable without Plotly toolbars."""
    lang = _lang(lang)
    key = INDICATORS[indicator]["key"]
    _, (raw_low, raw_high) = measure_bounds(indicator, view)

    if view == "all":
        scope = t("map.legend_shared", lang)
    else:
        scope = tf("map.legend_scaled", lang, country=country_adjective(view, lang))

    return [
        html.Div([
            html.Span(tf("map.legend_colour", lang, label=t(f"measure.{key}.label", lang)),
                      className="legend-title"),
            html.Span(scope, className="micro"),
        ], className="legend-head"),
        html.Div(
            className="legend-bar",
            style={"background": "linear-gradient(90deg," + ",".join(INDICATORS[indicator]["colors"]) + ")"},
        ),
        html.Div([
            html.Span(f"{fmt_value(indicator, raw_low, lang)} \u00b7 {t(f'measure.{key}.low', lang)}"),
            html.Span(f"{fmt_value(indicator, raw_high, lang)} \u00b7 {t(f'measure.{key}.high', lang)}"),
        ], className="legend-ticks"),
    ]


def build_map_note(indicator: str, view: str, lang: str | None = None):
    """One sentence that explains the current view, plus honest caveats."""
    lang = _lang(lang)
    spec = INDICATORS[indicator]
    key = spec["key"]
    rows = visible_rows(view).dropna(subset=[indicator])
    top = rows.sort_values(indicator, ascending=spec["ascending"]).iloc[0]

    parts = [
        html.B(tf(
            "map.note_top", lang,
            label=t(f"measure.{key}.top_label", lang),
            region=top["region_name"],
            value=fmt_value(indicator, top[indicator], lang),
        )),
        t("map.note_click", lang),
    ]
    if view == "all":
        parts.append(t("map.note_shared", lang))
    else:
        parts.append(t("map.note_fitted", lang))
    if spec.get("log"):
        parts.append(t("map.note_log", lang))
    if view in ("all", "USA"):
        parts.append(t("map.note_us", lang))
    return parts



def build_scatter(
    selected_region: str | None, view: str, lang: str | None = None,
) -> go.Figure:
    """Hazard against SHDI, one colour per country, selected region ringed."""
    lang = _lang(lang)
    data = visible_rows(view).dropna(subset=["hazard_equal", "shdi"]).copy()
    if data.empty:
        return empty_figure(t("relation.empty", lang))

    figure = go.Figure()

    for iso3 in COUNTRY_CODES:
        group = data[data["iso3"] == iso3]
        if group.empty:
            continue
        figure.add_trace(go.Scatter(
            x=group["hazard_equal"],
            y=group["shdi"],
            mode="markers",
            name=country_name(iso3, lang),
            marker={
                "size": 8,
                "color": COUNTRY_COLORS[iso3],
                "opacity": 0.82,
                "line": {"width": 0.6, "color": "#e9eddc"},
            },
            customdata=np.stack([
                group["region_name"].astype(str),
                group["risk_equal"].map(lambda v: t("misc.na", lang) if pd.isna(v) else f"{v:.3f}"),
                group["population"].map(lambda v: compact(v, lang)),
            ], axis=-1),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                f"{t('hover.hazard', lang)} %{{x:.3f}}<br>"
                f"{t('hover.shdi', lang)} %{{y:.3f}}<br>"
                f"{t('hover.risk', lang)} %{{customdata[1]}} \u00b7 "
                f"{t('hover.population', lang).lower()} %{{customdata[2]}}"
                "<extra></extra>"
            ),
        ))


    # One straight trend line per country (least squares). A single line
    # through all regions would mostly join India to the two other countries.
    for iso3 in COUNTRY_CODES:
        group = data[data["iso3"] == iso3]
        if len(group) < 5:
            continue
        slope, intercept = np.polyfit(group["hazard_equal"], group["shdi"], 1)
        x = np.linspace(group["hazard_equal"].min(), group["hazard_equal"].max(), 20)
        figure.add_trace(go.Scatter(
            x=x,
            y=intercept + slope * x,
            mode="lines",
            name=t("relation.trend", lang),
            line={"color": COUNTRY_COLORS[iso3], "width": 2},
            hoverinfo="skip",
            showlegend=False,
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
                name=t("relation.selected", lang),
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
        title={"text": t("relation.axis_x", lang), "font": {"size": 10}},
        range=[0, 1],
        gridcolor="rgba(106,12,6,0.14)",
        zeroline=False,
        linecolor="rgba(106,12,6,0.35)",
        ticks="outside",
        ticklen=4,
        tickfont={"size": 9},
    )
    figure.update_yaxes(
        title={"text": t("relation.axis_y", lang), "font": {"size": 10}},
        gridcolor="rgba(106,12,6,0.14)",
        zeroline=False,
        linecolor="rgba(106,12,6,0.35)",
        ticks="outside",
        ticklen=4,
        tickfont={"size": 9},
    )
    return figure


def build_profile_chart(region_id: str | None, lang: str | None = None) -> go.Figure:
    """Percentile position of one region, with its country median marked.

    Raw values are on very different scales (heat days vs an index from 0 to
    1), so comparing them on one axis is meaningless. Percentiles put them on
    a common 0-100 scale; the hover box still shows the real values.
    """
    lang = _lang(lang)
    if not region_id:
        return empty_figure(t("profile.empty", lang))

    row = DATA[DATA["region_id"] == region_id]
    if row.empty:
        return empty_figure(t("profile.not_found", lang))
    row = row.iloc[0]
    country = DATA[DATA["iso3"] == row["iso3"]]

    metrics = [
        (t("metric.risk", lang), "risk_equal"),
        (t("metric.vulnerability", lang), "vulnerability"),
        (t("metric.hazard", lang), "hazard_equal"),
        (t("metric.exposure", lang), "population"),
        (t("metric.heat", lang), "hd35_area"),
        (t("metric.shdi", lang), "shdi"),
    ]

    labels, position, hover = [], [], []
    country_position, country_hover = [], []

    for label, column in metrics:
        values = DATA[column]
        pct = percentile(values, row[column])
        position.append(0 if pct is None else pct)
        hover.append([
            fmt_value(column, row[column], lang) if column != "population" else compact(row[column], lang),
            t("misc.na", lang) if pct is None else tf("profile.percentile", lang, value=f"{pct:.0f}"),
        ])

        median = country[column].median()
        cpct = percentile(values, median)
        country_position.append(0 if cpct is None else cpct)
        country_hover.append([
            t("misc.na", lang) if pd.isna(median) else (
                compact(median, lang) if column == "population"
                else fmt_value(column, median, lang)
            ),
            t("misc.na", lang) if cpct is None else tf("profile.percentile", lang, value=f"{cpct:.0f}"),
        ])
        labels.append(label)

    figure = go.Figure()
    figure.add_trace(go.Bar(
        x=position,
        y=labels,
        orientation="h",
        name=t("profile.this_region", lang),
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
        name=t("profile.country_median", lang),
        marker={
            "symbol": "diamond",
            "size": 9,
            "color": DARK,
            "line": {"width": 1, "color": "#e9eddc"},
        },
        customdata=country_hover,
        hovertemplate=(
            f"<b>%{{y}}</b> \u00b7 {t('profile.country_median', lang)}<br>%{{customdata[0]}}<br>"
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
        title={"text": t("profile.axis", lang), "font": {"size": 10}},
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

def detail_rows(region_id: str | None, lang: str | None = None):
    """The region card shown in section 05."""
    lang = _lang(lang)
    if not region_id:
        return [html.P(t("profile.choose", lang), className="empty")]

    row = DATA[DATA["region_id"] == region_id]
    if row.empty:
        return [html.P(t("profile.not_found", lang), className="empty")]
    row = row.iloc[0]

    rank = row["risk_rank"]
    rank_text = t("misc.na", lang) if pd.isna(rank) else f"{int(rank):02d}"

    cells = [
        (t("detail.risk_rank", lang), rank_text, tf("detail.of_ranked", lang, n=N_RANKED)),
        (t("detail.risk_index", lang), fmt_value("risk_equal", row["risk_equal"], lang), ""),
        (t("detail.hazard_index", lang), fmt_value("hazard_equal", row["hazard_equal"], lang), ""),
        (t("detail.heat_days", lang), fmt_value("hd35_area", row["hd35_area"], lang), ""),
        (t("detail.population", lang), compact(row["population"], lang), ""),
        (t("detail.shdi", lang), fmt_value("shdi", row["shdi"], lang), ""),
        (t("detail.vulnerability", lang), fmt_value("vulnerability", row["vulnerability"], lang), ""),
        (t("detail.heat_exposure", lang), compact(row["person_days_heat"], lang),
         t("detail.person_days", lang)),
    ]

    return [
        html.P(
            f"{country_name(row['iso3'], lang)} \u00b7 {row['iso3']}",
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


def build_ranking(indicator: str, view: str, lang: str | None = None):
    """Top ten regions for the current measure and view.

    Returns the row elements, the matching region ids (for click handling)
    and a heading that names the measure.
    """
    lang = _lang(lang)
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
                        f"{row['iso3']} \u00b7 {country_name(row['iso3'], lang)}",
                        className="rank-country",
                    ),
                ], className="rank-who"),
                html.Span(
                    html.Span(style={"width": f"{max(2, min(100, width)):.1f}%"}),
                    className="rank-bar",
                ),
                html.Span(fmt_value(indicator, row[indicator], lang), className="rank-value"),
            ],
            id={"type": "rank-row", "index": number - 1},
            n_clicks=0,
            className="rank-row",
            title=tf("ranking.tooltip", lang, region=row["region_name"]),
        ))
        ids.append(str(row["region_id"]))

    return rows, ids, t(f"measure.{spec['key']}.rank_title", lang)


def ticker_segment(lang: str | None = None):
    """One copy of the number strip in the fixed header."""
    lang = _lang(lang)
    items = [
        ("105", t("ticker.regions", lang)),
        ("3", t("ticker.countries", lang)),
        (f"{num(TOTAL_POPULATION, 2, lang)}{BILLION_SUFFIX[lang]}", t("ticker.people", lang)),
        (num(MEDIAN_RISK, 3, lang), t("ticker.median_risk", lang)),
        (RHO_TEXT, t("ticker.rho", lang)),
        ("bih\u0101r", t("ticker.top_region", lang)),
    ]
    # Doubling the items makes the strip wider than most screens.
    doubled = items * 2
    return html.Div(
        [html.Span([html.B(value), f" {label}"]) for value, label in doubled],
        className="ticker-seg",
    )


METHODS = [
    ("method.hazard_title", "method.hazard_text"),
    ("method.exposure_title", "method.exposure_text"),
    ("method.vulnerability_title", "method.vulnerability_text"),
    ("method.risk_title", "method.risk_text"),
    ("method.statistics_title", "method.statistics_text"),
    ("method.scope_title", "method.scope_text"),
]



# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def language_switch(lang: str, page: str = "/") -> html.Div:
    """The EN / FR control in the top bar.

    A plain link rather than a callback: a full reload rebuilds every
    server-rendered string and every figure in one go, which keeps the
    implementation simple and the two languages impossible to mix.
    """
    def option(code: str, label: str, title: str):
        active = lang == code
        attributes = {"className": "lang-option is-current"}
        if active:
            attributes["aria-current"] = "true"
        else:
            attributes["className"] = "lang-option"
        return html.A(label, href=f"{page}?lang={code}", title=title, **attributes)

    globe = html.Span(className="lang-globe", **{"aria-hidden": "true"})

    return html.Div(
        [
            globe,
            option("en", "EN", t("misc.english", lang)),
            html.Span("/", className="lang-sep", **{"aria-hidden": "true"}),
            option("fr", "FR", t("misc.french", lang)),
        ],
        className="lang-switch",
        title=f"{t('misc.language', lang)}",
        **{"aria-label": t("misc.language", lang), "role": "group"},
    )


def layout(lang: str | None = None) -> html.Div:
    """Build the whole dashboard page in the chosen language."""
    lang = _lang(lang)
    report_href = "/report/fr" if lang == "fr" else "/report"
    pdf_href = "/report/fr.pdf" if lang == "fr" else "/report.pdf"

    initial_bounds, _ = measure_bounds("risk_equal", "all")
    initial_rows, initial_ids, initial_heading = build_ranking("risk_equal", "all", lang)
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
                    html.H3(country_adjective(iso3, lang), className="map-country"),
                    html.Span(
                        tf("map.region_count", lang, n=len(MAP_ROWS[iso3])),
                        className="map-meta",
                    ),
                ], className="map-panel-head"),
                dcc.Graph(
                    id=f"map-{iso3}",
                    figure=build_country_map("risk_equal", iso3, initial_bounds, 320, lang),
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
                html.Div([ticker_segment(lang), ticker_segment(lang)], className="ticker-track"),
                className="ticker",
            ),
            html.Nav([
                html.A(t("nav.map", lang), href="#map"),
                html.A(t("nav.ranking", lang), href="#ranking"),
                html.A(t("nav.relationship", lang), href="#relationship"),
                html.A(t("nav.profile", lang), href="#profile"),
                html.A(t("nav.methods", lang), href="#methods"),
                html.A(t("nav.summary", lang), href="/summary"),
            ], className="topnav"),
            language_switch(lang),
        ], className="topbar"),


        html.Main([
            # 01 - overview -------------------------------------------------
            html.Section([
                html.Div([
                    html.P(t("hero.eyebrow", lang), className="eyebrow"),
                    html.P(t("hero.scope", lang), className="eyebrow"),
                ], className="eyebrow-row"),

                html.H1([
                    t("hero.title_a", lang),
                    html.Span(t("hero.title_b", lang), className="light"),
                ]),

                html.Div([
                    html.Div([
                        html.P([
                            t("hero.lede_a", lang),
                            html.B(t("measure.hazard.chip", lang)), ", ",
                            html.B(t("measure.exposure.chip", lang)), t("misc.and", lang),
                            html.B(t("measure.vulnerability.chip", lang)),
                            t("hero.lede_b", lang),
                        ], className="lede"),
                        html.A(
                            [t("hero.summary_link", lang), html.Span("\u2192")],
                            href="/summary",
                            className="hero-link",
                        ),
                    ], className="hero-copy"),
                    html.Div([
                        html.Div([
                            html.Span(f"{N_REGIONS}", className="stat-value"),
                            html.Span(t("stat.regions", lang), className="stat-label"),
                        ], className="stat"),
                        html.Div([
                            html.Span(f"{N_COUNTRIES}", className="stat-value"),
                            html.Span(t("stat.countries", lang), className="stat-label"),
                        ], className="stat"),
                        html.Div([
                            html.Span(f"{num(TOTAL_POPULATION, 2, lang)}{BILLION_SUFFIX[lang]}",
                                      className="stat-value"),
                            html.Span(t("stat.people", lang), className="stat-label"),
                        ], className="stat"),
                        html.Div([
                            html.Span(RHO_TEXT, className="stat-value"),
                            html.Span(t("stat.rho", lang), className="stat-label"),
                        ], className="stat"),
                    ], className="stats"),
                ], className="hero-bottom"),
            ], className="hero", id="top"),


            # Controls ------------------------------------------------------
            html.Div([
                html.Div([
                    html.Div([
                        html.Span(t("controls.view", lang), className="control-label"),
                        dcc.RadioItems(
                            id="country-view",
                            options=[{"label": t(f"country.{value}", lang), "value": value}
                                     for value, _ in COUNTRY_CHOICES],
                            value="all",
                            inline=True,
                            className="chips",
                            labelClassName="chip",
                            inputClassName="chip-input",
                        ),
                    ], className="control-block"),
                    html.Div([
                        html.Span(t("controls.measure", lang), className="control-label"),
                        dcc.RadioItems(
                            id="measure",
                            options=[{"label": t(f"measure.{key}.chip", lang), "value": value}
                                     for value, key in MEASURE_CHOICES],
                            value="risk_equal",
                            inline=True,
                            className="chips",
                            labelClassName="chip",
                            inputClassName="chip-input",
                        ),
                    ], className="control-block"),
                    html.Div([
                        html.Span(t("controls.find", lang), className="control-label"),
                        dcc.Dropdown(
                            id="region-select",
                            options=region_options,
                            value=TOP_REGION,
                            clearable=False,
                            searchable=True,
                            placeholder=t("controls.search", lang),
                            className="region-dropdown",
                        ),
                    ], className="control-block control-region"),
                ], className="controls-grid"),
            ], className="controls", id="controls"),


            # 02 - map ------------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("02", className="section-num"),
                    html.H2(t("map.title", lang), className="section-title"),
                    html.P(t("map.desc", lang), className="section-desc"),
                ], className="section-head"),
                html.Div(map_panels, className="map-grid"),
                html.Div(build_legend("risk_equal", "all", lang), id="map-legend", className="map-legend"),
                html.P(build_map_note("risk_equal", "all", lang), id="map-note", className="map-note"),
            ], className="section", id="map"),

            # 03 - ranking --------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("03", className="section-num"),
                    html.H2(t("ranking.title", lang), className="section-title"),
                    html.P([
                        t("ranking.desc_a", lang),
                        html.Span(initial_heading, id="rank-heading"),
                        t("ranking.desc_b", lang),
                    ], className="section-desc"),
                ], className="section-head"),
                html.Div(initial_rows, id="rank-list", className="rank-list"),
                dcc.Store(id="rank-store", data=initial_ids),
            ], className="section", id="ranking"),


            # 04 - relationship ---------------------------------------------
            html.Section([
                html.Div([
                    html.Span("04", className="section-num"),
                    html.H2(t("relation.title", lang), className="section-title"),
                    html.P(t("relation.desc", lang), className="section-desc"),
                ], className="section-head"),
                html.Div([
                    html.Div([
                        dcc.Graph(
                            id="scatter-graph",
                            figure=build_scatter(TOP_REGION, "all", lang),
                            config={"displayModeBar": False, "responsive": True},
                        ),
                        html.P(t("relation.caption", lang), className="chart-caption"),
                    ], className="chart-panel"),
                    html.Div([
                        html.Span(RHO_TEXT, className="finding-big"),
                        html.Span(t("relation.finding", lang), className="finding-label"),
                        html.Ul([
                            html.Li([
                                html.B(t("relation.medians", lang)),
                                html.Span(result_text("relation.medians_text", lang)),
                            ]),
                            html.Li([
                                html.B(t("relation.within", lang)),
                                html.Span(result_text("relation.within_text", lang)),
                            ]),
                            html.Li([
                                html.B(t("relation.by_country", lang)),
                                html.Span(result_text("relation.by_country_text", lang)),
                            ]),
                            html.Li([
                                html.B(t("relation.stability", lang)),
                                html.Span(result_text("relation.stability_text", lang)),
                            ]),
                        ], className="finding-list"),
                    ], className="finding"),
                ], className="split section-body"),
            ], className="section", id="relationship"),

            # 05 - profile --------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("05", className="section-num"),
                    html.H2(t("profile.title", lang), className="section-title"),
                    html.P(t("profile.desc", lang), className="section-desc"),
                ], className="section-head"),
                html.Div([
                    html.Div(detail_rows(TOP_REGION, lang), id="region-detail", className="profile-card"),
                    html.Div([
                        dcc.Graph(
                            id="profile-graph",
                            figure=build_profile_chart(TOP_REGION, lang),
                            config={"displayModeBar": False, "responsive": True},
                        ),
                        html.P(t("profile.caption", lang), className="chart-caption"),
                    ], className="chart-panel"),
                ], className="split section-body"),
            ], className="section", id="profile"),

            # 06 - methods --------------------------------------------------
            html.Section([
                html.Div([
                    html.Span("06", className="section-num"),
                    html.H2(t("methods.title", lang), className="section-title"),
                    html.P(t("methods.desc", lang), className="section-desc"),
                ], className="section-head"),
                html.Div([
                    html.Div([
                        html.H3(t(heading, lang)),
                        html.P(t(text, lang)),
                    ], className="method")
                    for heading, text in METHODS
                ], className="methods-grid"),
                html.Div([
                    html.H3(t("methods.caveat_title", lang)),
                    html.P(t("methods.caveat_text", lang)),
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
                    html.Span(t("next.kicker", lang), className="next-kicker"),
                    html.H2(t("next.title", lang), className="next-title"),
                ], className="next-head"),
                html.Div([
                    html.A([
                        html.Span(t("next.summary_title", lang), className="next-link-title"),
                        html.Span(t("next.summary_meta", lang), className="next-link-meta"),
                    ], href="/summary", className="next-link"),
                    html.A([
                        html.Span(t("next.report_title", lang), className="next-link-title"),
                        html.Span(t("next.report_meta", lang), className="next-link-meta"),
                    ], href=report_href, className="next-link"),
                    html.A([
                        html.Span(t("next.pdf_title", lang), className="next-link-title"),
                        html.Span(t("next.pdf_meta", lang), className="next-link-meta"),
                    ], href=pdf_href, className="next-link"),
                ], className="next-links"),
            ], className="next-band"),
        ], className="shell"),

        html.Footer([
            html.Span(t("footer.line", lang)),
            html.Span(t("footer.stack", lang)),
        ], className="footer shell"),
    ], className="page")



# ---------------------------------------------------------------------------
# App and callbacks
# ---------------------------------------------------------------------------

def _validation_layout():
    """A copy of the layout used only to check that callback ids exist.

    When the layout is a function, Dash evaluates it once at start-up and
    embeds the result in the ``_dash-config`` block of every page. The real
    layout weighs several megabytes because the map figures carry their
    geometry, so every visit would download it twice: once in the page and
    once from ``/_dash-layout``. The figures are useless for id checking, so
    they are emptied here and the page stays a few kilobytes.
    """
    tree = layout("en")
    for part in tree._traverse():
        if isinstance(part, dcc.Graph):
            part.figure = {}
    return tree


def create_app() -> dash.Dash:
    """Create the Dash app, register its callbacks and the extra Flask pages."""
    assets_folder = str(__import__("pathlib").Path(__file__).with_name("assets"))
    application = dash.Dash(
        __name__,
        assets_folder=assets_folder,
        title="Climate Risk Observatory",
        update_title=None,
    )

    # Set before the layout: Dash then skips building its own copy.
    application.validation_layout = _validation_layout()

    # A function, not a fixed tree: Dash calls it on every /_dash-layout
    # request, so the page is rebuilt in the language of the reader.
    application.layout = lambda: layout(current_lang())

    # The written summary and the report files are plain Flask pages, not
    # Dash layouts: they never change, so they do not need callbacks.
    register_report_routes(application.server)

    @application.server.after_request
    def _remember_language(response):
        """Keep the chosen language for the next page.

        The switch links to ``?lang=fr`` (or ``en``). Remembering it in a
        cookie means the choice follows the reader from the dashboard to the
        summary and back without putting it in every URL.
        """
        chosen = request.args.get("lang")
        if chosen and normalize(chosen) in LANGS:
            response.set_cookie(
                COOKIE_NAME,
                normalize(chosen),
                max_age=60 * 60 * 24 * 365,
                samesite="Lax",
            )
        # The layout is language-dependent and must never come from a cache.
        if request.path == "/_dash-layout":
            response.headers["Cache-Control"] = "no-store"
        return response

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
        lang = current_lang()
        indicator = indicator or "risk_equal"
        view = view or "all"

        bounds, _ = measure_bounds(indicator, view)
        height = 560 if view != "all" else 320

        figures = {
            iso3: build_country_map(indicator, iso3, bounds, height, lang)
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

        rows, ids, heading = build_ranking(indicator, view, lang)
        return (
            figures["FRA"], figures["IND"], figures["USA"],
            classes["FRA"], classes["IND"], classes["USA"],
            build_legend(indicator, view, lang),
            build_map_note(indicator, view, lang),
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
        return detail_rows(region_id, current_lang())

    @application.callback(
        Output("scatter-graph", "figure"),
        Input("region-select", "value"),
        Input("country-view", "value"),
    )
    def _update_scatter(region_id, view):
        return build_scatter(region_id, view or "all", current_lang())

    @application.callback(
        Output("profile-graph", "figure"),
        Input("region-select", "value"),
    )
    def _update_profile(region_id):
        return build_profile_chart(region_id, current_lang())

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
