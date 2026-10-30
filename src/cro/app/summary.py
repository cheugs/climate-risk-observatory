"""The reader-facing summary page and the links to the full report.

The dashboard is deliberately visual. Some readers want the written argument
instead: the question, the method, the four findings, the tables and the
caveats. That is what this module builds.

The page is plain HTML rendered by Flask, not a Dash layout, because it has no
interactivity. It reuses the dashboard stylesheet (``/assets/style.css``) plus a
small extra sheet for the article layout. Numbers come from the same CSV tables
the report is built from, so the summary cannot drift away from the report.

Routes added by :func:`register_report_routes`:

``/summary``     this page
``/report``      the full Quarto report (self-contained HTML)
``/report.pdf``  the print version
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
from flask import send_from_directory

from cro.config import PROJECT_ROOT
from cro.utils import log

COUNTRIES = {
    "FRA": "France",
    "IND": "India",
    "USA": "United States",
}

TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
REPORT_DIR = PROJECT_ROOT / "outputs" / "report"


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _num(value, digits: int = 2) -> str:
    """Format a number with a real minus sign, for the editorial look."""
    if pd.isna(value):
        return "n/a"
    text = f"{value:,.{digits}f}"
    return text.replace("-", "\u2212")


def _p(value) -> str:
    """A p-value small enough to be interesting, without fake precision."""
    if pd.isna(value):
        return "n/a"
    if value < 0.001:
        return "&lt; 0.001"
    return _num(value, 3)


def _escape(text) -> str:
    return html.escape(str(text))


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------

def _stat(value: str, label: str) -> str:
    return (
        '<div class="report-stat">'
        f'<span class="stat-value">{value}</span>'
        f'<span class="stat-label">{label}</span>'
        "</div>"
    )


def _finding(value: str, title: str, body: str) -> str:
    return (
        '<div class="r-finding">'
        f'<div class="r-find-value">{value}</div>'
        '<div class="r-find-body">'
        f'<h3 class="r-find-title">{title}</h3>'
        f'<p>{body}</p>'
        "</div>"
        "</div>"
    )


def _top_table(top: pd.DataFrame) -> str:
    rows = []
    for row in top.itertuples():
        rows.append(
            "<tr>"
            f'<td class="num">{int(row.rank_equal):02d}</td>'
            f"<td>{_escape(row.region_name)}</td>"
            f"<td>{_escape(COUNTRIES.get(row.iso3, row.iso3))}</td>"
            f'<td class="num">{_num(row.risk_equal, 3)}</td>'
            f'<td class="num">{_num(row.population / 1e6, 1)}</td>'
            "</tr>"
        )
    return (
        '<div class="r-table-wrap">'
        '<table class="r-table">'
        '<caption class="r-caption">Ten highest composite-risk regions</caption>'
        "<thead><tr>"
        '<th class="num">#</th><th>Region</th><th>Country</th>'
        '<th class="num">Risk</th><th class="num">People (m)</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _country_table(summary: pd.DataFrame) -> str:
    order = ["FRA", "IND", "USA", "ALL"]
    labels = {**COUNTRIES, "ALL": "All three"}
    total_heat = float(summary.loc["ALL", "person_days_heat_bn"])
    rows = []
    for iso3 in order:
        row = summary.loc[iso3]
        share = 100 * float(row["person_days_heat_bn"]) / total_heat
        rows.append(
            "<tr>"
            f"<td>{labels[iso3]}</td>"
            f'<td class="num">{int(row["n_regions"])}</td>'
            f'<td class="num">{_num(row["population_m"], 1)}</td>'
            f'<td class="num">{_num(row["risk_median"], 3)}</td>'
            f'<td class="num">{_num(row["person_days_heat_bn"], 2)}</td>'
            f'<td class="num">{share:.1f}%</td>'
            "</tr>"
        )
    return (
        '<div class="r-table-wrap">'
        '<table class="r-table">'
        '<caption class="r-caption">Where the risk and the heat sit</caption>'
        "<thead><tr><th>Group</th>"
        '<th class="num">Regions</th><th class="num">People (m)</th>'
        '<th class="num">Median risk</th>'
        '<th class="num">Person-days (bn)</th><th class="num">Share</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        '<p class="r-source">Source: outputs/tables/t01_summary_by_country.csv. '
        "Share is the country's slice of all person-days of extreme heat in the "
        "pilot.</p>"
    )


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def build_summary_html(
    tables_dir: Path = TABLES_DIR,
    report_dir: Path = REPORT_DIR,
) -> str:
    """Render the whole summary page from the report tables."""
    summary = pd.read_csv(tables_dir / "t01_summary_by_country.csv").set_index("group")
    top = pd.read_csv(tables_dir / "t03_top_bottom_regions.csv")
    top = top[top["group"] == "highest_risk"].sort_values("rank_equal").head(10)
    tests = pd.read_csv(tables_dir / "t05_hypothesis_tests.csv")
    regression = pd.read_csv(tables_dir / "t07_regression_coefficients.csv")
    slopes = pd.read_csv(tables_dir / "t08_country_slopes.csv").set_index("iso3")
    moran = pd.read_csv(tables_dir / "t09_morans_i.csv")

    h1 = tests.iloc[0]
    h2 = tests.iloc[1]
    within = regression[
        (regression["model"] == "M3 country FE")
        & (regression["term"] == "hazard_equal_z")
    ].iloc[0]
    national = moran[moran["scope"] == "all countries"].set_index("variable")

    all_row = summary.loc["ALL"]
    india_heat = float(summary.loc["IND", "person_days_heat_bn"])
    india_share = 100 * india_heat / float(all_row["person_days_heat_bn"])

    report_exists = (report_dir / "report.html").exists()
    pdf_exists = (report_dir / "report.pdf").exists()

    # Hero numbers ---------------------------------------------------------
    stats = "".join([
        _stat(_num(all_row["n_regions"], 0), "admin-1 regions"),
        _stat(f'{_num(all_row["population_m"] / 1000, 2)}bn', "people covered"),
        _stat(f'{_num(h1["concentration_ratio"], 2)}&times;', "heat exposure concentration"),
        _stat(_num(h2["spearman_rho"], 2), "hazard-SHDI rank correlation"),
    ])

    # Ticker: two identical segments so the CSS loop is seamless. ----------
    ticker_segment = (
        '<div class="ticker-seg">'
        f'<span><b>{int(all_row["n_regions"])}</b> regions</span>'
        f'<span><b>{len(COUNTRIES)}</b> countries</span>'
        f'<span><b>{_num(all_row["population_m"] / 1000, 2)}bn</b> people</span>'
        f'<span><b>{_num(h1["concentration_ratio"], 2)}&times;</b> concentration</span>'
        f'<span><b>{_num(h2["spearman_rho"], 2)}</b> rank correlation</span>'
        "</div>"
    )

    top_table = _top_table(top)
    country_table = _country_table(summary)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Summary &middot; Climate Risk &amp; Human Development Observatory</title>
<link rel="stylesheet" href="/assets/style.css">
<link rel="stylesheet" href="/assets/summary.css">
</head>
<body class="report-page">

<div class="grid-overlay" aria-hidden="true">
  <span></span><span></span><span></span><span></span><span></span><span></span>
  <span></span><span></span><span></span><span></span><span></span><span></span>
</div>

<header class="topbar">
  <a class="brand" href="/">cro.</a>
  <div class="ticker">
    <div class="ticker-track">{ticker_segment}{ticker_segment}</div>
  </div>
  <nav class="topnav">
    <a href="/">dashboard</a>
    <a href="/summary" class="is-current" aria-current="page">summary</a>
    <a href="/report">full report</a>
  </nav>
</header>

<main class="page">
  <div class="shell">

    <section class="report-hero">
      <div class="eyebrow-row">
        <p class="eyebrow">summary &amp; report &middot; pilot edition</p>
        <p class="eyebrow">france / india / united states</p>
      </div>
      <h1 class="report-title">the summary<span>of the statistical report.</span></h1>
      <p class="report-standfirst">
        A two-minute read of the written report: the question, how the index is
        built, the four findings, the tables behind them and the limits of what
        they can say. Every number here is generated from the same tables as the
        full document, so the two cannot disagree.
      </p>
      <div class="report-stats">{stats}</div>
    </section>

    <div class="report-layout">
      <article class="report-body">

        <section class="r-section" id="question">
          <div class="r-head"><span class="r-num">01</span><h2 class="r-title">the question</h2></div>
          <p class="r-text">
            Do the places exposed to the most climate stress also have the
            lowest human development? And if so, is that just a country effect,
            or does it hold among regions inside the same country?
          </p>
          <p class="r-text">
            The pilot covers {int(all_row["n_regions"])} admin-1 regions in
            France, India and the United States: {_num(all_row["population_m"] / 1000, 2)}
            billion people. Climate is measured from NASA POWER daily records
            (1991&ndash;2023), population from the 2020 GHS-POP grid, and
            development from the subnational Human Development Index (SHDI).
          </p>
        </section>

        <section class="r-section" id="method">
          <div class="r-head"><span class="r-num">02</span><h2 class="r-title">how the index is built</h2></div>
          <div class="r-cards">
            <div class="r-card">
              <h3>hazard</h3>
              <p>Six climate measures (days above 35&nbsp;&deg;C, tropical nights,
              dry-spell length, water balance, heaviest rain, very wet days) are
              turned into percentiles, then averaged into heat, dry and wet
              sub-indices.</p>
            </div>
            <div class="r-card">
              <h3>exposure</h3>
              <p>Population times heat days. Each person is assigned to the
              nearest climate sample point, so a hot but empty region does not
              rank like a hot and crowded one.</p>
            </div>
            <div class="r-card">
              <h3>vulnerability</h3>
              <p>One minus the percentile rank of SHDI. Lower development means
              higher vulnerability. Regions with no SHDI keep their hazard and
              exposure scores but are left out of the development models.</p>
            </div>
            <div class="r-card">
              <h3>risk</h3>
              <p>The geometric mean of hazard, exposure and vulnerability
              (IPCC framing). A region must score on all three to rank high.
              Additive and PCA-weighted versions are kept as robustness checks.</p>
            </div>
          </div>
          <p class="r-source">All ingredients are percentiles from 0 to 1, which is
          why the composite risk index is also on a 0&ndash;1 scale.</p>
        </section>

        <section class="r-section" id="findings">
          <div class="r-head"><span class="r-num">03</span><h2 class="r-title">what we found</h2></div>
          {_finding(
              f'{_num(h1["concentration_ratio"], 2)}&times;',
              "Exposure is concentrated",
              "The top 10% most hazardous regions hold "
              f'{_num(h1["concentration_ratio"], 2)} times their population share '
              f'of person-days of extreme heat (95% CI {_num(h1["ci_low"], 2)} to '
              f'{_num(h1["ci_high"], 2)}). Heat exposure is not spread evenly '
              "across the pilot.",
          )}
          {_finding(
              f'{_num(h2["median_shdi_high_hazard"], 3)} <span class="r-vs">vs</span> '
              f'{_num(h2["median_shdi_low_hazard"], 3)}',
              "High hazard goes with lower development",
              "Median SHDI is "
              f'{_num(h2["median_shdi_high_hazard"], 3)} in high-hazard regions and '
              f'{_num(h2["median_shdi_low_hazard"], 3)} in low-hazard regions '
              f'(Mann&ndash;Whitney p {_p(h2["p_value"])}, Cliff&rsquo;s &delta; '
              f'{_num(h2["cliffs_delta"], 2)}). The rank correlation is '
              f'{_num(h2["spearman_rho"], 2)}.',
          )}
          {_finding(
              _num(within["beta"], 2),
              "It survives country fixed effects",
              "A one standard deviation rise in hazard goes with "
              f'{_num(within["beta"], 2)} standard deviations of SHDI inside '
              f'countries (95% CI {_num(within["ci_low"], 2)} to '
              f'{_num(within["ci_high"], 2)}, N = {int(within["n_obs"])}). The slope is '
              f'{_num(slopes.loc["IND", "slope"], 2)} in India and '
              f'{_num(slopes.loc["USA", "slope"], 2)} in the United States; in France it is '
              f'{_num(slopes.loc["FRA", "slope"], 2)} because the hazard range is narrow.',
          )}
          {_finding(
              _num(national.loc["risk_equal", "morans_i"], 2),
              "The pattern is spatially clustered",
              "Moran&rsquo;s I is "
              f'{_num(national.loc["risk_equal", "morans_i"], 2)} for composite risk, '
              f'{_num(national.loc["hazard_equal", "morans_i"], 2)} for hazard and '
              f'{_num(national.loc["shdi", "morans_i"], 2)} for SHDI (all p &le; 0.001): '
              "neighbouring regions resemble each other, so the map is not noise. "
              "The exception is SHDI in France, where I = "
              f'{_num(moran[(moran["scope"] == "FRA") & (moran["variable"] == "shdi")].iloc[0]["morans_i"], 2)} '
              "and the clustering is not significant.",
          )}
        </section>

        <section class="r-section" id="places">
          <div class="r-head"><span class="r-num">04</span><h2 class="r-title">where the risk sits</h2></div>
          <p class="r-text">
            All ten of the highest-risk regions are in India, and India accounts
            for {india_share:.0f}% of all person-days of extreme heat in the
            pilot. The ranking is a screening tool, not a verdict: it says
            where to look first.
          </p>
          {top_table}
          {country_table}
        </section>

        <section class="r-section" id="limits">
          <div class="r-head"><span class="r-num">05</span><h2 class="r-title">what would change the answer</h2></div>
          <ul class="r-list">
            <li><b>Association, not causation.</b> Climate, history, institutions
            and geography are entangled. The models show a robust association;
            they do not identify a causal effect.</li>
            <li><b>Six regions have no SHDI.</b> Development tests use 99 of the
            105 regions; hazard, exposure and risk still cover all 105.</li>
            <li><b>Admin-1 boundaries are coarse.</b> A large region can hide a
            hot city, and a small one can look worse than its surroundings.</li>
            <li><b>One development indicator.</b> SHDI does not capture inequality
            inside a region, which is often the part that matters for adaptation.</li>
            <li><b>Historical climate only.</b> The index describes 1991&ndash;2023,
            not future scenarios. A CMIP6 appendix is deliberately left out.</li>
            <li><b>Three countries.</b> The pipeline scales to roughly 3,700
            regions, but the findings are a pilot, not a global result.</li>
          </ul>
        </section>

        <section class="r-section r-read" id="read">
          <div class="r-head"><span class="r-num">06</span><h2 class="r-title">read the full report</h2></div>
          <p class="r-text">
            The complete document adds the literature, the regression tables,
            the spatial diagnostics, all eleven maps and the eleven figures.
            Both versions are self-contained files.
          </p>
          <div class="r-read-links">
            <a class="r-read-link" href="/report">
              <span class="r-read-kicker">html &middot; opens in this tab</span>
              <span class="r-read-title">the full report <span aria-hidden="true">&rarr;</span></span>
            </a>
            <a class="r-read-link" href="/report.pdf">
              <span class="r-read-kicker">pdf &middot; print layout</span>
              <span class="r-read-title">download the pdf <span aria-hidden="true">&darr;</span></span>
            </a>
          </div>
          <p class="r-source">Tables behind this page: outputs/tables/t01&ndash;t09.
          Report source: outputs/report/report.html and report.pdf.</p>
        </section>

      </article>

      <aside class="report-aside">
        <div class="aside-box">
          <span class="micro">on this page</span>
          <ul>
            <li><a href="#question">01 &middot; the question</a></li>
            <li><a href="#method">02 &middot; how the index is built</a></li>
            <li><a href="#findings">03 &middot; what we found</a></li>
            <li><a href="#places">04 &middot; where the risk sits</a></li>
            <li><a href="#limits">05 &middot; what would change the answer</a></li>
            <li><a href="#read">06 &middot; read the full report</a></li>
          </ul>
        </div>
        <div class="aside-box">
          <span class="micro">the document</span>
          {'<a class="aside-link" href="/report">open report.html &rarr;</a>' if report_exists else ''}
          {'<a class="aside-link" href="/report.pdf">report.pdf &darr;</a>' if pdf_exists else ''}
          <a class="aside-link" href="/">back to the dashboard &rarr;</a>
        </div>
      </aside>
    </div>

    <footer class="footer">
      <span>climate risk &amp; human development observatory &middot; pilot edition</span>
      <span><a href="/">dashboard</a> &middot; <a href="/report">report</a> &middot; python &middot; postgis &middot; plotly</span>
    </footer>

  </div>
</main>

</body>
</html>
"""


def _fallback_html(message: str) -> str:
    """A readable page even when the report tables have not been built yet."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Summary &middot; Climate Risk Observatory</title>
<link rel="stylesheet" href="/assets/style.css">
<link rel="stylesheet" href="/assets/summary.css"></head>
<body class="report-page"><main class="page"><div class="shell">
<p class="eyebrow">summary &amp; report</p>
<h1 class="report-title">the summary<span>is not available yet.</span></h1>
<p class="report-standfirst">
The report tables could not be read, so this page cannot show its numbers.
Run the analysis and the report first, then reload.
</p>
<pre class="r-source">{_escape(message)}</pre>
<p><a href="/">back to the dashboard &rarr;</a></p>
</div></main></body></html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_report_routes(server, tables_dir: Path = TABLES_DIR) -> None:
    """Add /summary, /report and /report.pdf to the Dash Flask server."""
    report_dir = REPORT_DIR
    try:
        page = build_summary_html(tables_dir, report_dir)
    except Exception as error:  # noqa: BLE001 - the page must never break the app
        log(f"summary page: could not build from tables ({error})")
        page = _fallback_html(str(error))

    @server.route("/summary")
    def summary_page():
        return page

    @server.route("/report")
    def full_report():
        return send_from_directory(report_dir, "report.html")

    @server.route("/report.pdf")
    def report_pdf():
        return send_from_directory(report_dir, "report.pdf")
