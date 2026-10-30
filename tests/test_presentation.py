"""Smoke tests for the presentation layer: geometry loading, maps, dashboard.

Why smoke tests instead of detailed ones: the figures and the dashboard are
mostly glue code. The realistic failure mode is not a wrong number, it is a
crash (missing column, geometry in the wrong format, a callback that cannot
build its figure). These tests exercise those paths cheaply.

Run them with:  pytest -q
"""

from __future__ import annotations

import pandas as pd
import pytest
import shapely
import shapely.wkb

from cro.utils import load_geo_table


# ---------------------------------------------------------------------------
# Geometry loading
# ---------------------------------------------------------------------------

def test_load_geo_table_repairs_wkb_bytes(tmp_path):
    """Regression test for a real bug.

    GeoPandas writes proper GeoParquet, but plain pandas writes the geometry
    column as raw WKB bytes. Reading that back gives a DataFrame whose
    "geometry" column is a column of bytes, and plotting fails with
    "Input must be valid geometry objects". `load_geo_table` must fix it.
    """
    shapes = [shapely.Point(2.35, 48.85), shapely.Point(77.2, 28.6)]
    wkb = [shapely.wkb.dumps(shape) for shape in shapes]

    # Deliberately write a plain DataFrame, not a GeoDataFrame.
    frame = pd.DataFrame({"region_id": ["FR", "IN"], "geometry": wkb})
    path = tmp_path / "broken.parquet"
    frame.to_parquet(path, index=False)

    repaired = load_geo_table(path)

    assert repaired.crs is not None
    assert str(repaired.crs) == "EPSG:4326"
    assert repaired.geometry.iloc[0].x == pytest.approx(2.35)
    # Coordinates survive the round trip.
    assert repaired.geometry.iloc[1].y == pytest.approx(28.6)


def test_load_geo_table_leaves_good_files_alone(tmp_path):
    """A proper GeoParquet file must load unchanged."""
    import geopandas as gpd

    original = gpd.GeoDataFrame(
        {"region_id": ["A"]},
        geometry=[shapely.Point(0, 0)],
        crs="EPSG:4326",
    )
    path = tmp_path / "good.parquet"
    original.to_parquet(path)

    loaded = load_geo_table(path)
    assert isinstance(loaded, gpd.GeoDataFrame)
    assert len(loaded) == 1


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_builds_with_expected_callbacks():
    """The app object must exist and expose the interactive callbacks."""
    from cro.app.app import create_app

    application = create_app()

    assert application.layout is not None
    assert len(application.callback_map) >= 5


def test_map_figure_has_data():
    """Each country map must draw its regions as filled polygons."""
    from cro.app.app import build_country_map, measure_bounds

    bounds, _ = measure_bounds("risk_equal", "all")
    for iso3 in ("FRA", "IND", "USA"):
        figure = build_country_map("risk_equal", iso3, bounds)

        assert len(figure.data) >= 10
        assert figure.data[0].type == "scatter"
        assert len(figure.data[0].x) >= 4
        assert figure.data[0].fill == "toself"


def test_ranking_and_detail_build():
    """The ranking and the region card are plain HTML built from the data."""
    from cro.app.app import DATA, build_ranking, detail_rows

    rows, ids, heading = build_ranking("risk_equal", "IND")
    top_region = DATA.sort_values("risk_equal", ascending=False).iloc[0]["region_id"]

    assert len(rows) == 10
    assert len(ids) == 10
    assert ids[0] == top_region
    assert isinstance(heading, str) and heading
    assert len(detail_rows(top_region)) >= 3


def test_scatter_and_profile_figures_build():
    """The relationship and profile charts must produce a figure."""
    from cro.app.app import DATA, build_profile_chart, build_scatter

    region_id = DATA.sort_values("risk_equal", ascending=False).iloc[0]["region_id"]

    scatter = build_scatter(region_id, None)
    profile = build_profile_chart(region_id)

    assert len(scatter.data) >= 1
    assert len(profile.data) >= 1


def test_dashboard_payloads_are_plain_json():
    """Regression test for a bug that only appeared in the browser.

    Shapely objects cannot be sent to the browser, so every figure payload
    must be serialisable. The app now projects geometry into plain numbers
    before building the map, and this test makes sure that stays true.
    """
    import plotly.io as pio

    from cro.app.app import DATA, build_country_map, build_profile_chart, measure_bounds

    bounds, _ = measure_bounds("risk_equal", "all")
    top_region = DATA.sort_values("risk_equal", ascending=False).iloc[0]["region_id"]
    pio.to_json(build_country_map("risk_equal", "FRA", bounds))
    pio.to_json(build_profile_chart(top_region))


# ---------------------------------------------------------------------------
# Summary page and report links
# ---------------------------------------------------------------------------

def test_summary_page_builds_from_the_report_tables():
    """The reading page must show the same numbers as the report tables."""
    from cro.app.summary import build_summary_html

    page = build_summary_html()

    assert "the summary" in page
    assert "the question" in page
    assert "what we found" in page
    assert "1.38" in page           # H1 concentration ratio
    assert "0.786" in page          # median SHDI, high hazard
    assert "0.936" in page          # median SHDI, low hazard
    assert "/report.pdf" in page
    assert "/assets/summary.css" in page


def test_summary_page_has_a_french_version():
    """The French page must be translated, not the English page relabelled."""
    from cro.app.summary import build_summary_html

    page = build_summary_html(lang="fr")

    assert "la synthèse" in page
    assert "ce que nous avons trouvé" in page
    assert "1,38" in page           # French decimal comma
    assert "0,786" in page
    assert "/report/fr.pdf" in page
    assert "the summary" not in page
    assert 'href="/summary?lang=en"' in page


def test_every_interface_string_has_a_french_translation():
    """A missing translation would show English inside the French page."""
    from cro.app.i18n import TEXTS, keys_missing_french

    assert keys_missing_french() == []
    assert all(isinstance(pair, tuple) and len(pair) == 2 for pair in TEXTS.values())


def test_summary_and_report_routes_respond():
    """Flask must serve the summary, the HTML report and the PDF."""
    from cro.app.app import create_app

    client = create_app().server.test_client()

    summary = client.get("/summary")
    assert summary.status_code == 200
    assert b"the statistical report" in summary.data

    report = client.head("/report")
    assert report.status_code == 200
    assert "text/html" in report.headers["Content-Type"]

    pdf = client.head("/report.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["Content-Type"] == "application/pdf"


def test_french_summary_and_report_routes_respond():
    """The French summary and both French report files must be reachable."""
    from cro.app.app import create_app

    client = create_app().server.test_client()

    summary = client.get("/summary?lang=fr")
    assert summary.status_code == 200
    assert "la synthèse" in summary.data.decode("utf-8")
    assert summary.headers.get("Set-Cookie", "").startswith("cro_lang=fr")

    report = client.head("/report/fr")
    assert report.status_code == 200
    assert "text/html" in report.headers["Content-Type"]

    pdf = client.head("/report/fr.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["Content-Type"] == "application/pdf"


def test_dashboard_layout_switches_language():
    """The layout is rebuilt per request, in the language of the reader."""
    from cro.app.app import create_app

    client = create_app().server.test_client()

    french = client.get("/_dash-layout?lang=fr")
    english = client.get("/_dash-layout?lang=en")

    assert french.status_code == 200
    assert english.status_code == 200
    assert "la carte." in french.data.decode("utf-8")
    assert "the map." in english.data.decode("utf-8")
    assert "?lang=en" in french.data.decode("utf-8")
    assert "lang-option is-current" in french.data.decode("utf-8")
    assert "Cache-Control" in french.headers
    assert french.headers["Cache-Control"] == "no-store"
