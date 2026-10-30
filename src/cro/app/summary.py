"""The reader-facing summary page and the links to the full report.

The dashboard is deliberately visual. Some readers want the written argument
instead: the question, the method, the four findings, the tables and the
caveats. That is what this module builds.

The page is plain HTML rendered by Flask, not a Dash layout, because it has no
interactivity. It reuses the dashboard stylesheet (``/assets/style.css``) plus a
small extra sheet for the article layout. Numbers come from the same CSV tables
the report is built from, so the summary cannot drift away from the report.

Every string exists in English and French; the language follows the ``lang``
query parameter or the ``cro_lang`` cookie set by the switch in the header.

Routes added by :func:`register_report_routes`:

``/summary``         this page, in the reader's language
``/report``          the full Quarto report (self-contained HTML, English)
``/report.pdf``      the print version, English
``/report/fr``       the French report
``/report/fr.pdf``   the French print version
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
from flask import make_response, send_from_directory

from cro.app.i18n import current_lang, num, t
from cro.config import PROJECT_ROOT
from cro.utils import log

COUNTRIES = {
    "FRA": "France",
    "IND": "India",
    "USA": "United States",
}
COUNTRIES_FR = {
    "FRA": "France",
    "IND": "Inde",
    "USA": "États-Unis",
}

TABLES_DIR = PROJECT_ROOT / "outputs" / "tables"
REPORT_DIR = PROJECT_ROOT / "outputs" / "report"

REPORT_FILES = {
    "en": ("report.html", "report.pdf"),
    "fr": ("report.fr.html", "report.fr.pdf"),
}


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _num(value, digits: int = 2, lang: str = "en") -> str:
    """Format a number with a real minus sign, for the editorial look."""
    return num(value, digits, lang)


def _p(value, lang: str = "en") -> str:
    """A p-value small enough to be interesting, without fake precision."""
    if pd.isna(value):
        return t("misc.na", lang)
    if value < 0.001:
        return "&lt; 0,001" if lang == "fr" else "&lt; 0.001"
    return _num(value, 3, lang)


def _escape(text) -> str:
    return html.escape(str(text))


def _country(iso3: str, lang: str) -> str:
    table = COUNTRIES_FR if lang == "fr" else COUNTRIES
    return table.get(iso3, iso3)


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


def _top_table(top: pd.DataFrame, lang: str) -> str:
    rows = []
    for row in top.itertuples():
        rows.append(
            "<tr>"
            f'<td class="num">{int(row.rank_equal):02d}</td>'
            f"<td>{_escape(row.region_name)}</td>"
            f"<td>{_escape(_country(row.iso3, lang))}</td>"
            f'<td class="num">{_num(row.risk_equal, 3, lang)}</td>'
            f'<td class="num">{_num(row.population / 1e6, 1, lang)}</td>'
            "</tr>"
        )
    caption = ("Ten highest composite-risk regions" if lang == "en"
               else "Dix régions au risque composite le plus élevé")
    headers = (('#', 'Region', 'Country', 'Risk', 'People (m)') if lang == "en"
               else ('#', 'Région', 'Pays', 'Risque', 'Population (M)'))
    return (
        '<div class="r-table-wrap">'
        '<table class="r-table">'
        f'<caption class="r-caption">{caption}</caption>'
        "<thead><tr>"
        f'<th class="num">{headers[0]}</th><th>{headers[1]}</th><th>{headers[2]}</th>'
        f'<th class="num">{headers[3]}</th><th class="num">{headers[4]}</th>'
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def _country_table(summary: pd.DataFrame, lang: str) -> str:
    order = ["FRA", "IND", "USA", "ALL"]
    labels = {iso3: _country(iso3, lang) for iso3 in ("FRA", "IND", "USA")}
    labels["ALL"] = "All three" if lang == "en" else "Les trois"
    total_heat = float(summary.loc["ALL", "person_days_heat_bn"])
    rows = []
    for iso3 in order:
        row = summary.loc[iso3]
        share = 100 * float(row["person_days_heat_bn"]) / total_heat
        rows.append(
            "<tr>"
            f"<td>{labels[iso3]}</td>"
            f'<td class="num">{int(row["n_regions"])}</td>'
            f'<td class="num">{_num(row["population_m"], 1, lang)}</td>'
            f'<td class="num">{_num(row["risk_median"], 3, lang)}</td>'
            f'<td class="num">{_num(row["person_days_heat_bn"], 2, lang)}</td>'
            f'<td class="num">{_num(share, 1, lang)}{"&nbsp;%" if lang == "fr" else "%"}</td>'
            "</tr>"
        )
    if lang == "en":
        caption = "Where the risk and the heat sit"
        headers = ('<th>Group</th>'
                   '<th class="num">Regions</th><th class="num">People (m)</th>'
                   '<th class="num">Median risk</th>'
                   '<th class="num">Person-days (bn)</th><th class="num">Share</th>')
        source = ("Source: outputs/tables/t01_summary_by_country.csv. "
                  "Share is the country's slice of all person-days of extreme heat in the "
                  "pilot.")
    else:
        caption = "Où se situent le risque et la chaleur"
        headers = ('<th>Groupe</th>'
                   '<th class="num">Régions</th><th class="num">Population (M)</th>'
                   '<th class="num">Risque médian</th>'
                   '<th class="num">Jours-personnes (Md)</th><th class="num">Part</th>')
        source = ("Source : outputs/tables/t01_summary_by_country.csv. "
                  "La part est la fraction du pays dans l'ensemble des jours-personnes "
                  "de chaleur extrême du pilote.")
    return (
        '<div class="r-table-wrap">'
        '<table class="r-table">'
        f'<caption class="r-caption">{caption}</caption>'
        f"<thead><tr>{headers}</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
        f'<p class="r-source">{source}</p>'
    )


# ---------------------------------------------------------------------------
# The prose, per language
# ---------------------------------------------------------------------------

def _copy(lang: str, values: dict) -> dict[str, str]:
    """Every sentence on the page, in one language.

    ``values`` holds the already-formatted numbers so the two languages can
    never disagree about a figure.
    """
    v = values
    if lang == "fr":
        c = {
            "lang": "fr",
            "title": "Synthèse &middot; Observatoire du risque climatique &amp; du développement humain",
            "eyebrow": "synthèse &amp; rapport &middot; édition pilote",
            "scope": "france / inde / états-unis",
            "hero_title": "la synthèse<span>du rapport statistique.</span>",
            "standfirst": (
                "Une lecture de deux minutes du rapport écrit : la question, la "
                "construction de l'indice, les quatre constats, les tableaux qui les "
                "étayent et les limites de ce qu'ils peuvent dire. Chaque chiffre est "
                "produit à partir des mêmes tableaux que le document complet : les "
                "deux ne peuvent pas diverger."
            ),
            "stat_regions": "régions admin-1",
            "stat_people": "personnes couvertes",
            "stat_concentration": "concentration de l'exposition",
            "stat_rho": "corrélation aléa-IDH",
            "q_num": "01", "q_title": "la question",
            "q_text1": (
                "Les lieux les plus exposés au stress climatique sont-ils aussi ceux "
                "où le développement humain est le plus faible ? Et si oui, s'agit-il "
                "seulement d'un effet pays, ou cela tient-il aussi entre les régions "
                "d'un même pays ?"
            ),
            "q_text2": (
                f"Le pilote couvre {v['n_regions']} régions admin-1 en France, en Inde "
                f"et aux États-Unis : {v['population_bn']} milliards de personnes. Le "
                "climat est mesuré à partir des relevés quotidiens NASA POWER "
                "(1991&ndash;2023), la population à partir de la grille GHS-POP 2020, "
                "et le développement à partir de l'indice de développement humain "
                "infranational (IDH-S)."
            ),
            "m_num": "02", "m_title": "comment l'indice est construit",
            "card_hazard": "aléa",
            "card_hazard_text": (
                "Six mesures climatiques (jours au-dessus de 35&nbsp;&deg;C, nuits "
                "tropicales, durée de la sécheresse, bilan hydrique, pluie "
                "journalière maximale, jours très humides) sont converties en "
                "centiles, puis moyennées en sous-indices chaleur, sécheresse et "
                "humidité."
            ),
            "card_exposure": "exposition",
            "card_exposure_text": (
                "Population &times; jours de chaleur. Chaque personne est rattachée au "
                "point climatique le plus proche : une région chaude mais vide ne se "
                "classe donc pas comme une région chaude et densément peuplée."
            ),
            "card_vulnerability": "vulnérabilité",
            "card_vulnerability_text": (
                "Un moins le rang centile de l'IDH-S. Un développement plus faible "
                "signifie une vulnérabilité plus forte. Les régions sans IDH-S "
                "conservent leurs scores d'aléa et d'exposition mais sont exclues des "
                "modèles de développement."
            ),
            "card_risk": "risque",
            "card_risk_text": (
                "La moyenne géométrique de l'aléa, de l'exposition et de la "
                "vulnérabilité (cadre du GIEC). Une région doit être élevée sur les "
                "trois pour bien se classer. Des versions additive et pondérée par "
                "ACP servent de tests de robustesse."
            ),
            "method_source": (
                "Tous les ingrédients sont des centiles de 0 à 1, ce qui explique que "
                "l'indice de risque composite soit lui aussi sur une échelle de 0 à 1."
            ),
            "f_num": "03", "f_title": "ce que nous avons trouvé",
            "find1_title": "L'exposition est concentrée",
            "find1_body": (
                f"Les 10&nbsp;% de régions les plus exposées à l'aléa concentrent "
                f"{v['ratio']} fois leur part de population en jours-personnes de "
                f"chaleur extrême (IC à 95&nbsp;% : {v['ci_low']} à {v['ci_high']}). "
                "L'exposition à la chaleur n'est pas répartie uniformément dans le "
                "pilote."
            ),
            "find2_title": "Un aléa élevé va de pair avec un développement plus faible",
            "find2_body": (
                f"L'IDH-S médian est de {v['median_high']} dans les régions à fort "
                f"aléa et de {v['median_low']} dans celles à faible aléa "
                f"(Mann&ndash;Whitney p {v['p_value']}, delta de Cliff "
                f"{v['cliffs']}). La corrélation de rang est de {v['rho']}."
            ),
            "find3_title": "L'effet résiste aux effets fixes pays",
            "find3_body": (
                f"Une hausse d'un écart-type de l'aléa correspond à {v['beta']} "
                f"écart-type d'IDH-S à l'intérieur des pays (IC à 95&nbsp;% : "
                f"{v['beta_low']} à {v['beta_high']}, N = {v['n_obs']}). La pente est "
                f"de {v['slope_ind']} en Inde et de {v['slope_usa']} aux États-Unis ; "
                f"en France, elle est de {v['slope_fra']} car la plage d'aléa est "
                "étroite."
            ),
            "find4_title": "Le motif est spatialement agrégé",
            "find4_body": (
                f"Le I de Moran est de {v['moran_risk']} pour le risque composite, "
                f"{v['moran_hazard']} pour l'aléa et {v['moran_shdi']} pour l'IDH-S "
                "(tous p &le; 0,001) : les régions voisines se ressemblent, la carte "
                "n'est donc pas du bruit. L'exception est l'IDH-S en France, où "
                f"I = {v['moran_fra_shdi']} et l'agrégation n'est pas significative."
            ),
            "p_num": "04", "p_title": "où se situe le risque",
            "p_text": (
                "Les dix régions les plus à risque sont toutes en Inde, et l'Inde "
                f"concentre {v['india_share']}&nbsp;% de tous les jours-personnes de "
                "chaleur extrême du pilote. Le classement est un outil de repérage, "
                "pas un verdict : il indique où regarder d'abord."
            ),
            "l_num": "05", "l_title": "ce qui changerait la réponse",
            "limit1_b": "Association, pas causalité.",
            "limit1": (
                "Climat, histoire, institutions et géographie sont enchevêtrés. Les "
                "modèles montrent une association robuste ; ils n'identifient pas un "
                "effet causal."
            ),
            "limit2_b": "Six régions n'ont pas d'IDH-S.",
            "limit2": (
                "Les tests de développement portent sur 99 des 105 régions ; l'aléa, "
                "l'exposition et le risque couvrent toujours les 105."
            ),
            "limit3_b": "Les limites admin-1 sont grossières.",
            "limit3": (
                "Une grande région peut cacher une ville surchauffée, et une petite "
                "peut sembler pire que son environnement."
            ),
            "limit4_b": "Un seul indicateur de développement.",
            "limit4": (
                "L'IDH-S ne saisit pas les inégalités à l'intérieur d'une région, "
                "souvent la dimension qui compte pour l'adaptation."
            ),
            "limit5_b": "Climat historique uniquement.",
            "limit5": (
                "L'indice décrit 1991&ndash;2023, pas des scénarios futurs. Une annexe "
                "CMIP6 est volontairement laissée de côté."
            ),
            "limit6_b": "Trois pays.",
            "limit6": (
                "Le pipeline passe à l'échelle d'environ 3 700 régions, mais les "
                "résultats sont un pilote, pas un résultat mondial."
            ),
            "r_num": "06", "r_title": "lire le rapport complet",
            "r_text": (
                "Le document complet ajoute la littérature, les tableaux de "
                "régression, les diagnostics spatiaux, les onze cartes et les onze "
                "figures. Les deux versions sont des fichiers autonomes."
            ),
            "read_html_kicker": "html &middot; s'ouvre dans cet onglet",
            "read_html_title": "le rapport complet",
            "read_pdf_kicker": "pdf &middot; mise en page imprimée",
            "read_pdf_title": "télécharger le pdf",
            "sources": (
                "Tableaux derrière cette page : outputs/tables/t01&ndash;t09. Source "
                "du rapport : outputs/report/report.fr.html et report.fr.pdf."
            ),
            "aside_on_page": "sur cette page",
            "toc_1": "01 &middot; la question",
            "toc_2": "02 &middot; comment l'indice est construit",
            "toc_3": "03 &middot; ce que nous avons trouvé",
            "toc_4": "04 &middot; où se situe le risque",
            "toc_5": "05 &middot; ce qui changerait la réponse",
            "toc_6": "06 &middot; lire le rapport complet",
            "aside_doc": "le document",
            "aside_html": "ouvrir report.html &rarr;",
            "aside_pdf": "rapport.pdf &darr;",
            "aside_back": "retour au tableau de bord &rarr;",
            "footer_left": (
                "observatoire du risque climatique &amp; du développement humain "
                "&middot; édition pilote"
            ),
            "footer_link_dashboard": "tableau de bord",
            "footer_link_report": "rapport",
        }
    else:
        c = {
            "lang": "en",
            "title": "Summary &middot; Climate Risk &amp; Human Development Observatory",
            "eyebrow": "summary &amp; report &middot; pilot edition",
            "scope": "france / india / united states",
            "hero_title": "the summary<span>of the statistical report.</span>",
            "standfirst": (
                "A two-minute read of the written report: the question, how the index "
                "is built, the four findings, the tables behind them and the limits of "
                "what they can say. Every number here is generated from the same "
                "tables as the full document, so the two cannot disagree."
            ),
            "stat_regions": "admin-1 regions",
            "stat_people": "people covered",
            "stat_concentration": "heat exposure concentration",
            "stat_rho": "hazard-SHDI rank correlation",
            "q_num": "01", "q_title": "the question",
            "q_text1": (
                "Do the places exposed to the most climate stress also have the "
                "lowest human development? And if so, is that just a country effect, "
                "or does it hold among regions inside the same country?"
            ),
            "q_text2": (
                f"The pilot covers {v['n_regions']} admin-1 regions in France, India "
                f"and the United States: {v['population_bn']} billion people. Climate "
                "is measured from NASA POWER daily records (1991&ndash;2023), "
                "population from the 2020 GHS-POP grid, and development from the "
                "subnational Human Development Index (SHDI)."
            ),
            "m_num": "02", "m_title": "how the index is built",
            "card_hazard": "hazard",
            "card_hazard_text": (
                "Six climate measures (days above 35&nbsp;&deg;C, tropical nights, "
                "dry-spell length, water balance, heaviest rain, very wet days) are "
                "turned into percentiles, then averaged into heat, dry and wet "
                "sub-indices."
            ),
            "card_exposure": "exposure",
            "card_exposure_text": (
                "Population times heat days. Each person is assigned to the nearest "
                "climate sample point, so a hot but empty region does not rank like a "
                "hot and crowded one."
            ),
            "card_vulnerability": "vulnerability",
            "card_vulnerability_text": (
                "One minus the percentile rank of SHDI. Lower development means higher "
                "vulnerability. Regions with no SHDI keep their hazard and exposure "
                "scores but are left out of the development models."
            ),
            "card_risk": "risk",
            "card_risk_text": (
                "The geometric mean of hazard, exposure and vulnerability (IPCC "
                "framing). A region must score on all three to rank high. Additive and "
                "PCA-weighted versions are kept as robustness checks."
            ),
            "method_source": (
                "All ingredients are percentiles from 0 to 1, which is why the "
                "composite risk index is also on a 0&ndash;1 scale."
            ),
            "f_num": "03", "f_title": "what we found",
            "find1_title": "Exposure is concentrated",
            "find1_body": (
                "The top 10% most hazardous regions hold "
                f"{v['ratio']} times their population share of person-days of extreme "
                f"heat (95% CI {v['ci_low']} to {v['ci_high']}). Heat exposure is not "
                "spread evenly across the pilot."
            ),
            "find2_title": "High hazard goes with lower development",
            "find2_body": (
                f"Median SHDI is {v['median_high']} in high-hazard regions and "
                f"{v['median_low']} in low-hazard regions (Mann&ndash;Whitney p "
                f"{v['p_value']}, Cliff&rsquo;s &delta; {v['cliffs']}). The rank "
                f"correlation is {v['rho']}."
            ),
            "find3_title": "It survives country fixed effects",
            "find3_body": (
                "A one standard deviation rise in hazard goes with "
                f"{v['beta']} standard deviations of SHDI inside countries (95% CI "
                f"{v['beta_low']} to {v['beta_high']}, N = {v['n_obs']}). The slope is "
                f"{v['slope_ind']} in India and {v['slope_usa']} in the United States; "
                f"in France it is {v['slope_fra']} because the hazard range is narrow."
            ),
            "find4_title": "The pattern is spatially clustered",
            "find4_body": (
                f"Moran&rsquo;s I is {v['moran_risk']} for composite risk, "
                f"{v['moran_hazard']} for hazard and {v['moran_shdi']} for SHDI (all "
                "p &le; 0.001): neighbouring regions resemble each other, so the map "
                "is not noise. The exception is SHDI in France, where I = "
                f"{v['moran_fra_shdi']} and the clustering is not significant."
            ),
            "p_num": "04", "p_title": "where the risk sits",
            "p_text": (
                "All ten of the highest-risk regions are in India, and India accounts "
                f"for {v['india_share']}% of all person-days of extreme heat in the "
                "pilot. The ranking is a screening tool, not a verdict: it says where "
                "to look first."
            ),
            "l_num": "05", "l_title": "what would change the answer",
            "limit1_b": "Association, not causation.",
            "limit1": (
                "Climate, history, institutions and geography are entangled. The "
                "models show a robust association; they do not identify a causal "
                "effect."
            ),
            "limit2_b": "Six regions have no SHDI.",
            "limit2": (
                "Development tests use 99 of the 105 regions; hazard, exposure and "
                "risk still cover all 105."
            ),
            "limit3_b": "Admin-1 boundaries are coarse.",
            "limit3": (
                "A large region can hide a hot city, and a small one can look worse "
                "than its surroundings."
            ),
            "limit4_b": "One development indicator.",
            "limit4": (
                "SHDI does not capture inequality inside a region, which is often the "
                "part that matters for adaptation."
            ),
            "limit5_b": "Historical climate only.",
            "limit5": (
                "The index describes 1991&ndash;2023, not future scenarios. A CMIP6 "
                "appendix is deliberately left out."
            ),
            "limit6_b": "Three countries.",
            "limit6": (
                "The pipeline scales to roughly 3,700 regions, but the findings are a "
                "pilot, not a global result."
            ),
            "r_num": "06", "r_title": "read the full report",
            "r_text": (
                "The complete document adds the literature, the regression tables, the "
                "spatial diagnostics, all eleven maps and the eleven figures. Both "
                "versions are self-contained files."
            ),
            "read_html_kicker": "html &middot; opens in this tab",
            "read_html_title": "the full report",
            "read_pdf_kicker": "pdf &middot; print layout",
            "read_pdf_title": "download the pdf",
            "sources": (
                "Tables behind this page: outputs/tables/t01&ndash;t09. Report source: "
                "outputs/report/report.html and report.pdf."
            ),
            "aside_on_page": "on this page",
            "toc_1": "01 &middot; the question",
            "toc_2": "02 &middot; how the index is built",
            "toc_3": "03 &middot; what we found",
            "toc_4": "04 &middot; where the risk sits",
            "toc_5": "05 &middot; what would change the answer",
            "toc_6": "06 &middot; read the full report",
            "aside_doc": "the document",
            "aside_html": "open report.html &rarr;",
            "aside_pdf": "report.pdf &darr;",
            "aside_back": "back to the dashboard &rarr;",
            "footer_left": (
                "climate risk &amp; human development observatory &middot; pilot edition"
            ),
            "footer_link_dashboard": "dashboard",
            "footer_link_report": "report",
        }
    return c


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

def build_summary_html(
    tables_dir: Path = TABLES_DIR,
    report_dir: Path = REPORT_DIR,
    lang: str = "en",
) -> str:
    """Render the whole summary page from the report tables."""
    lang = "fr" if str(lang).lower().startswith("fr") else "en"

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

    report_html, report_pdf = REPORT_FILES[lang]
    report_exists = (report_dir / report_html).exists()
    pdf_exists = (report_dir / report_pdf).exists()

    report_href = "/report/fr" if lang == "fr" else "/report"
    pdf_href = "/report/fr.pdf" if lang == "fr" else "/report.pdf"

    values = {
        "n_regions": f"{int(all_row['n_regions'])}",
        "population_bn": _num(all_row["population_m"] / 1000, 2, lang),
        "ratio": _num(h1["concentration_ratio"], 2, lang),
        "ci_low": _num(h1["ci_low"], 2, lang),
        "ci_high": _num(h1["ci_high"], 2, lang),
        "median_high": _num(h2["median_shdi_high_hazard"], 3, lang),
        "median_low": _num(h2["median_shdi_low_hazard"], 3, lang),
        "p_value": _p(h2["p_value"], lang),
        "cliffs": _num(h2["cliffs_delta"], 2, lang),
        "rho": _num(h2["spearman_rho"], 2, lang),
        "beta": _num(within["beta"], 2, lang),
        "beta_low": _num(within["ci_low"], 2, lang),
        "beta_high": _num(within["ci_high"], 2, lang),
        "n_obs": f"{int(within['n_obs'])}",
        "slope_ind": _num(slopes.loc["IND", "slope"], 2, lang),
        "slope_usa": _num(slopes.loc["USA", "slope"], 2, lang),
        "slope_fra": _num(slopes.loc["FRA", "slope"], 2, lang),
        "moran_risk": _num(national.loc["risk_equal", "morans_i"], 2, lang),
        "moran_hazard": _num(national.loc["hazard_equal", "morans_i"], 2, lang),
        "moran_shdi": _num(national.loc["shdi", "morans_i"], 2, lang),
        "moran_fra_shdi": _num(
            moran[(moran["scope"] == "FRA") & (moran["variable"] == "shdi")].iloc[0]["morans_i"],
            2, lang,
        ),
        "india_share": _num(india_share, 0, lang),
    }
    c = _copy(lang, values)

    # Hero numbers ---------------------------------------------------------
    stats = "".join([
        _stat(values["n_regions"], c["stat_regions"]),
        _stat(f'{values["population_bn"]}{" Md" if lang == "fr" else "bn"}', c["stat_people"]),
        _stat(f'{values["ratio"]}&times;', c["stat_concentration"]),
        _stat(values["rho"], c["stat_rho"]),
    ])

    # Ticker: two identical segments so the CSS loop is seamless. ----------
    ticker_segment = (
        '<div class="ticker-seg">'
        f'<span><b>{values["n_regions"]}</b> '
        f'{"régions" if lang == "fr" else "regions"}</span>'
        f'<span><b>{len(COUNTRIES)}</b> {"pays" if lang == "fr" else "countries"}</span>'
        f'<span><b>{values["population_bn"]}{" Md" if lang == "fr" else "bn"}</b> '
        f'{"personnes" if lang == "fr" else "people"}</span>'
        f'<span><b>{values["ratio"]}&times;</b> '
        f'{"concentration" if lang == "fr" else "concentration"}</span>'
        f'<span><b>{values["rho"]}</b> '
        f'{"corrélation de rang" if lang == "fr" else "rank correlation"}</span>'
        "</div>"
    )

    top_table = _top_table(top, lang)
    country_table = _country_table(summary, lang)

    return _page(c, values, stats, ticker_segment, top_table, country_table,
                 report_href, pdf_href, report_exists, pdf_exists)


def _page(
    c: dict, values: dict, stats: str, ticker_segment: str, top_table: str,
    country_table: str, report_href: str, pdf_href: str,
    report_exists: bool, pdf_exists: bool,
) -> str:
    """The shared page skeleton, filled with one language's copy."""

    def finding(value: str, title: str, body: str) -> str:
        return _finding(value, title, body)

    findings = "".join([
        finding(f'{values["ratio"]}&times;', c["find1_title"], c["find1_body"]),
        finding(
            f'{values["median_high"]} <span class="r-vs">{"vs" if c["lang"] == "en" else "contre"}</span> '
            f'{values["median_low"]}',
            c["find2_title"], c["find2_body"],
        ),
        finding(
            values["beta"],
            c["find3_title"],
            c["find3_body"],
        ),
        finding(
            values["moran_risk"],
            c["find4_title"],
            c["find4_body"],
        ),
    ])

    limit_items = "".join(
        f"<li><b>{c[f'limit{i}_b']}</b> {c[f'limit{i}']}</li>" for i in range(1, 7)
    )

    toc = "".join(
        f'<li><a href="#{anchor}">{c[f"toc_{i}"]}</a></li>'
        for i, anchor in enumerate(
            ("question", "method", "findings", "places", "limits", "read"), start=1
        )
    )

    aside_links = ""
    if report_exists:
        aside_links += f'<a class="aside-link" href="{report_href}">{c["aside_html"]}</a>'
    if pdf_exists:
        aside_links += f'<a class="aside-link" href="{pdf_href}">{c["aside_pdf"]}</a>'

    return f"""<!doctype html>
<html lang="{c['lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{c['title']}</title>
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
    <a href="/">{c['footer_link_dashboard']}</a>
    <a href="/summary" class="is-current" aria-current="page">{t("nav.summary", c["lang"])}</a>
    <a href="{report_href}">{c['footer_link_report']}</a>
  </nav>
  <div class="lang-switch" role="group" aria-label="{t("misc.language", c["lang"])}"
       title="{t('misc.language', c['lang'])}">
    <span class="lang-globe" aria-hidden="true"></span>
    <a class="lang-option{' is-current' if c['lang'] == 'en' else ''}" href="/summary?lang=en"
       title="{t('misc.english', c['lang'])}"{' aria-current="true"' if c['lang'] == 'en' else ''}>EN</a>
    <span class="lang-sep" aria-hidden="true">/</span>
    <a class="lang-option{' is-current' if c['lang'] == 'fr' else ''}" href="/summary?lang=fr"
       title="{t('misc.french', c['lang'])}"{' aria-current="true"' if c['lang'] == 'fr' else ''}>FR</a>
  </div>
</header>

<main class="page">
  <div class="shell">

    <section class="report-hero">
      <div class="eyebrow-row">
        <p class="eyebrow">{c['eyebrow']}</p>
        <p class="eyebrow">{c['scope']}</p>
      </div>
      <h1 class="report-title">{c['hero_title']}</h1>
      <p class="report-standfirst">{c['standfirst']}</p>
      <div class="report-stats">{stats}</div>
    </section>

    <div class="report-layout">
      <article class="report-body">

        <section class="r-section" id="question">
          <div class="r-head"><span class="r-num">{c['q_num']}</span><h2 class="r-title">{c['q_title']}</h2></div>
          <p class="r-text">{c['q_text1']}</p>
          <p class="r-text">{c['q_text2']}</p>
        </section>

        <section class="r-section" id="method">
          <div class="r-head"><span class="r-num">{c['m_num']}</span><h2 class="r-title">{c['m_title']}</h2></div>
          <div class="r-cards">
            <div class="r-card">
              <h3>{c['card_hazard']}</h3>
              <p>{c['card_hazard_text']}</p>
            </div>
            <div class="r-card">
              <h3>{c['card_exposure']}</h3>
              <p>{c['card_exposure_text']}</p>
            </div>
            <div class="r-card">
              <h3>{c['card_vulnerability']}</h3>
              <p>{c['card_vulnerability_text']}</p>
            </div>
            <div class="r-card">
              <h3>{c['card_risk']}</h3>
              <p>{c['card_risk_text']}</p>
            </div>
          </div>
          <p class="r-source">{c['method_source']}</p>
        </section>

        <section class="r-section" id="findings">
          <div class="r-head"><span class="r-num">{c['f_num']}</span><h2 class="r-title">{c['f_title']}</h2></div>
          {findings}
        </section>

        <section class="r-section" id="places">
          <div class="r-head"><span class="r-num">{c['p_num']}</span><h2 class="r-title">{c['p_title']}</h2></div>
          <p class="r-text">{c['p_text']}</p>
          {top_table}
          {country_table}
        </section>

        <section class="r-section" id="limits">
          <div class="r-head"><span class="r-num">{c['l_num']}</span><h2 class="r-title">{c['l_title']}</h2></div>
          <ul class="r-list">{limit_items}</ul>
        </section>

        <section class="r-section r-read" id="read">
          <div class="r-head"><span class="r-num">{c['r_num']}</span><h2 class="r-title">{c['r_title']}</h2></div>
          <p class="r-text">{c['r_text']}</p>
          <div class="r-read-links">
            <a class="r-read-link" href="{report_href}">
              <span class="r-read-kicker">{c['read_html_kicker']}</span>
              <span class="r-read-title">{c['read_html_title']} <span aria-hidden="true">&rarr;</span></span>
            </a>
            <a class="r-read-link" href="{pdf_href}">
              <span class="r-read-kicker">{c['read_pdf_kicker']}</span>
              <span class="r-read-title">{c['read_pdf_title']} <span aria-hidden="true">&darr;</span></span>
            </a>
          </div>
          <p class="r-source">{c['sources']}</p>
        </section>

      </article>

      <aside class="report-aside">
        <div class="aside-box">
          <span class="micro">{c['aside_on_page']}</span>
          <ul>{toc}</ul>
        </div>
        <div class="aside-box">
          <span class="micro">{c['aside_doc']}</span>
          {aside_links}
          <a class="aside-link" href="/">{c['aside_back']}</a>
        </div>
      </aside>
    </div>

    <footer class="footer">
      <span>{c['footer_left']}</span>
      <span><a href="/">{c['footer_link_dashboard']}</a> &middot; <a href="{report_href}">{c['footer_link_report']}</a> &middot; python &middot; postgis &middot; plotly</span>
    </footer>

  </div>
</main>

</body>
</html>
"""


def _fallback_html(message: str, lang: str = "en") -> str:
    """A readable page even when the report tables have not been built yet."""
    if lang == "fr":
        title = "Synthèse &middot; Observatoire du risque climatique"
        eyebrow = "synthèse &amp; rapport"
        heading = "la synthèse<span>n'est pas encore disponible.</span>"
        body = (
            "Les tableaux du rapport n'ont pas pu être lus : cette page ne peut pas "
            "afficher ses chiffres. Lancez l'analyse puis le rapport, et rechargez."
        )
        back = "retour au tableau de bord &rarr;"
    else:
        title = "Summary &middot; Climate Risk Observatory"
        eyebrow = "summary &amp; report"
        heading = "the summary<span>is not available yet.</span>"
        body = (
            "The report tables could not be read, so this page cannot show its "
            "numbers. Run the analysis and the report first, then reload."
        )
        back = "back to the dashboard &rarr;"
    return f"""<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<title>{title}</title>
<link rel="stylesheet" href="/assets/style.css">
<link rel="stylesheet" href="/assets/summary.css"></head>
<body class="report-page"><main class="page"><div class="shell">
<p class="eyebrow">{eyebrow}</p>
<h1 class="report-title">{heading}</h1>
<p class="report-standfirst">{body}</p>
<pre class="r-source">{_escape(message)}</pre>
<p><a href="/">{back}</a></p>
</div></main></body></html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def register_report_routes(server, tables_dir: Path = TABLES_DIR) -> None:
    """Add /summary, /report and their translations to the dash Flask server."""
    report_dir = REPORT_DIR
    pages: dict[str, str] = {}

    def page(lang: str) -> str:
        if lang not in pages:
            try:
                pages[lang] = build_summary_html(tables_dir, report_dir, lang)
            except Exception as error:  # noqa: BLE001 - the page must never break the app
                log(f"summary page ({lang}): could not build from tables ({error})")
                pages[lang] = _fallback_html(str(error), lang)
        return pages[lang]

    @server.route("/summary")
    def summary_page():
        response = make_response(page(current_lang()))
        response.headers["Cache-Control"] = "no-store"
        return response

    @server.route("/report")
    def full_report():
        return send_from_directory(report_dir, "report.html")

    @server.route("/report.pdf")
    def report_pdf():
        return send_from_directory(report_dir, "report.pdf")

    @server.route("/report/fr")
    def full_report_fr():
        return send_from_directory(report_dir, "report.fr.html")

    @server.route("/report/fr.pdf")
    def report_pdf_fr():
        return send_from_directory(report_dir, "report.fr.pdf")
