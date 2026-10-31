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
from flask import abort, make_response, send_from_directory

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
MAPS_DIR = PROJECT_ROOT / "outputs" / "maps"

# The four interactive maps the report links to. Listed explicitly so the
# route cannot be used to read anything else in outputs/maps.
INTERACTIVE_MAPS = {
    "map_web_risk.html",
    "map_web_hazard.html",
    "map_web_exposure.html",
    "map_web_shdi.html",
}

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
            "eyebrow": "synthèse &amp; rapport &middot; projet pilote",
            "scope": "france / inde / états-unis",
            "hero_title": "la synthèse<span>du rapport.</span>",
            "standfirst": (
                "Le rapport en deux minutes : la question, la construction de "
                "l'indice, les quatre résultats et leurs limites. Tous les chiffres "
                "viennent des mêmes tableaux que le rapport complet."
            ),
            "stat_regions": "régions admin-1",
            "stat_people": "personnes couvertes",
            "stat_rho": "corrélation aléa-IDH (toutes régions)",
            "stat_within": "effet de l'aléa dans les pays",
            "q_num": "01", "q_title": "la question",
            "q_text1": (
                "Les régions les plus exposées aux extrêmes climatiques sont-elles "
                "aussi celles où le développement humain est le plus faible ? Et "
                "est-ce encore vrai quand on compare les régions d'un même pays ?"
            ),
            "q_text2": (
                f"Le projet couvre {v['n_regions']} régions (États, provinces, régions) "
                f"en France, en Inde et aux États-Unis, soit {v['population_bn']} "
                "milliards de personnes. Le climat vient de NASA POWER "
                "(1991&ndash;2023), la population de GHS-POP 2020 et le développement "
                "de l'indice de développement humain infranational (IDH-S)."
            ),
            "m_num": "02", "m_title": "comment l'indice est construit",
            "card_hazard": "aléa",
            "card_hazard_text": (
                "Six mesures climatiques (jours au-dessus de 35&nbsp;&deg;C, nuits "
                "tropicales, plus longue période sèche, bilan hydrique, plus forte "
                "pluie en un jour, jours très pluvieux). Chacune devient un rang de "
                "0 à 1, puis on fait la moyenne chaleur / sec / humide."
            ),
            "card_exposure": "exposition",
            "card_exposure_text": (
                "Le nombre d'habitants de la région, transformé en rang de 0 à 1. On "
                "n'utilise pas la chaleur ici, car elle est déjà dans l'aléa : sinon "
                "elle serait comptée deux fois."
            ),
            "card_vulnerability": "vulnérabilité",
            "card_vulnerability_text": (
                "1 moins le rang de l'IDH-S. Un développement faible donne une "
                "vulnérabilité forte. Les 6 régions sans IDH-S n'ont pas de score de "
                "risque."
            ),
            "card_risk": "risque",
            "card_risk_text": (
                "Aléa &times; exposition &times; vulnérabilité (idée du GIEC). Une "
                "région doit être haute sur les trois pour avoir un risque élevé. "
                "Deux autres versions (moyenne simple, et risque sans la population) "
                "servent à vérifier le classement."
            ),
            "method_source": (
                "Tous les scores sont des rangs entre 0 et 1, donc le risque est "
                "aussi entre 0 et 1."
            ),
            "f_num": "03", "f_title": "les résultats",
            "find1_title": "Plus d'aléa, moins de développement (H1)",
            "find1_body": (
                f"Sur toutes les régions, la corrélation de Spearman entre l'aléa et "
                f"l'IDH-S est de {v['rho']} (p {v['p_value']}). L'IDH-S médian est de "
                f"{v['median_high']} dans la moitié la plus exposée et de "
                f"{v['median_low']} dans l'autre moitié. Mais cet écart vient surtout "
                "de la différence entre l'Inde et les deux autres pays."
            ),
            "find2_title": "Pays par pays, le lien est plus faible (H1)",
            "find2_body": (
                f"La corrélation est de {v['rho_ind']} en Inde et de {v['rho_usa']} aux "
                f"États-Unis. En France elle est de {v['rho_fra']} (p = {v['p_fra']}) : "
                "pas de lien visible, mais il n'y a que 13 régions et peu de "
                "différences de climat."
            ),
            "find3_title": "Le lien reste négatif dans les pays (H2)",
            "find3_body": (
                f"Dans une régression linéaire, le coefficient de l'aléa passe de "
                f"{v['beta_all']} à {v['beta']} quand on ajoute un effet pays "
                f"(IC à 95&nbsp;% : {v['beta_low']} à {v['beta_high']}, "
                f"N = {v['n_obs']}). Concrètement : +0,1 d'aléa va avec "
                f"{v['beta_tenth']} d'IDH-S, à pays égal."
            ),
            "find4_title": "Le classement est stable (H3)",
            "find4_body": (
                f"Entre les trois versions de l'indice, la corrélation des rangs est "
                f"d'au moins {v['min_rho']}, et au moins {v['min_top10']} des 10 "
                "premières régions sont les mêmes. Même sans la population, les "
                "grands États indiens restent en tête : ce n'est pas seulement un "
                "effet de taille."
            ),
            "p_num": "04", "p_title": "où se situe le risque",
            "p_text": (
                "Les dix régions les plus à risque sont toutes en Inde, car l'Inde "
                "a un climat plus chaud et un IDH-S moyen plus faible. Pour voir les "
                "différences en France ou aux États-Unis, choisissez un pays dans le "
                "tableau de bord. Le classement indique où regarder en premier ; ce "
                "n'est pas un verdict."
            ),
            "l_num": "05", "l_title": "les limites",
            "limit1_b": "Association, pas causalité.",
            "limit1": (
                "Le climat, l'histoire et l'économie sont liés. Les modèles montrent "
                "un lien, pas une cause."
            ),
            "limit2_b": "Six régions n'ont pas d'IDH-S.",
            "limit2": (
                "Les tests utilisent 99 régions sur 105 ; l'aléa couvre toujours les "
                "105."
            ),
            "limit3_b": "Les régions voisines se ressemblent.",
            "limit3": (
                "Les observations ne sont pas vraiment indépendantes, donc les "
                "p-values sont sans doute trop petites. Un modèle spatial serait "
                "l'étape suivante."
            ),
            "limit4_b": "Un seul indicateur de développement.",
            "limit4": (
                "L'IDH-S ne montre pas les inégalités à l'intérieur d'une région."
            ),
            "limit5_b": "Des seuils fixes.",
            "limit5": (
                "35&nbsp;&deg;C et 50&nbsp;mm sont des choix : la France a presque "
                "zéro jour au-dessus de 35&nbsp;&deg;C."
            ),
            "limit6_b": "Trois pays seulement.",
            "limit6": (
                "Les résultats viennent d'un pilote, pas d'une étude mondiale."
            ),
            "r_num": "06", "r_title": "lire le rapport complet",
            "r_text": (
                "Le rapport complet contient la méthode détaillée, tous les tableaux, "
                "les onze cartes et les six figures."
            ),
            "read_html_kicker": "html &middot; s'ouvre dans cet onglet",
            "read_html_title": "le rapport complet",
            "read_pdf_kicker": "pdf &middot; version imprimable",
            "read_pdf_title": "télécharger le pdf",
            "sources": (
                "Tableaux utilisés : outputs/tables/t01&ndash;t08. Rapport : "
                "outputs/report/report.fr.html et report.fr.pdf."
            ),
            "aside_on_page": "sur cette page",
            "toc_1": "01 &middot; la question",
            "toc_2": "02 &middot; comment l'indice est construit",
            "toc_3": "03 &middot; les résultats",
            "toc_4": "04 &middot; où se situe le risque",
            "toc_5": "05 &middot; les limites",
            "toc_6": "06 &middot; lire le rapport complet",
            "aside_doc": "le document",
            "aside_html": "ouvrir report.html &rarr;",
            "aside_pdf": "rapport.pdf &darr;",
            "aside_back": "retour au tableau de bord &rarr;",
            "footer_left": (
                "observatoire du risque climatique &amp; du développement humain "
                "&middot; projet pilote"
            ),
            "footer_link_dashboard": "tableau de bord",
            "footer_link_report": "rapport",
        }
    else:
        c = {
            "lang": "en",
            "title": "Summary &middot; Climate Risk &amp; Human Development Observatory",
            "eyebrow": "summary &amp; report &middot; pilot project",
            "scope": "france / india / united states",
            "hero_title": "the summary<span>of the report.</span>",
            "standfirst": (
                "The report in two minutes: the question, how the index is built, the "
                "four results and their limits. Every number comes from the same "
                "tables as the full report."
            ),
            "stat_regions": "admin-1 regions",
            "stat_people": "people covered",
            "stat_rho": "hazard-SHDI correlation (all regions)",
            "stat_within": "hazard effect inside countries",
            "q_num": "01", "q_title": "the question",
            "q_text1": (
                "Are the regions with the most extreme climate also the regions with "
                "the lowest human development? And is this still true when we compare "
                "regions of the same country?"
            ),
            "q_text2": (
                f"The project covers {v['n_regions']} regions (states, provinces, "
                f"regions) in France, India and the United States: "
                f"{v['population_bn']} billion people. Climate data come from NASA "
                "POWER (1991&ndash;2023), population from GHS-POP 2020 and "
                "development from the Subnational Human Development Index (SHDI)."
            ),
            "m_num": "02", "m_title": "how the index is built",
            "card_hazard": "hazard",
            "card_hazard_text": (
                "Six climate measures (days above 35&nbsp;&deg;C, tropical nights, "
                "longest dry spell, water balance, heaviest one-day rain, very wet "
                "days). Each one becomes a rank from 0 to 1, then we average heat, "
                "dry and wet."
            ),
            "card_exposure": "exposure",
            "card_exposure_text": (
                "The number of people living in the region, as a rank from 0 to 1. We "
                "do not use heat here, because heat is already in the hazard score; "
                "otherwise it would be counted twice."
            ),
            "card_vulnerability": "vulnerability",
            "card_vulnerability_text": (
                "1 minus the rank of SHDI. Low development means high vulnerability. "
                "The 6 regions without SHDI have no risk score."
            ),
            "card_risk": "risk",
            "card_risk_text": (
                "Hazard &times; exposure &times; vulnerability (IPCC idea). A region "
                "must be high on all three to get a high risk. Two other versions "
                "(simple mean, and risk without population) are used to check the "
                "ranking."
            ),
            "method_source": (
                "All scores are ranks between 0 and 1, so the risk is also between 0 "
                "and 1."
            ),
            "f_num": "03", "f_title": "the results",
            "find1_title": "More hazard, less development (H1)",
            "find1_body": (
                f"On all regions, the Spearman correlation between hazard and SHDI is "
                f"{v['rho']} (p {v['p_value']}). Median SHDI is {v['median_high']} in "
                f"the more hazardous half and {v['median_low']} in the other half. "
                "But this gap comes mostly from the difference between India and the "
                "two other countries."
            ),
            "find2_title": "Country by country, the link is weaker (H1)",
            "find2_body": (
                f"The correlation is {v['rho_ind']} in India and {v['rho_usa']} in "
                f"the United States. In France it is {v['rho_fra']} (p = "
                f"{v['p_fra']}): no clear link, but France has only 13 regions and "
                "small climate differences."
            ),
            "find3_title": "The link stays negative inside countries (H2)",
            "find3_body": (
                f"In a linear regression, the hazard coefficient goes from "
                f"{v['beta_all']} to {v['beta']} when we add a country effect (95% CI "
                f"{v['beta_low']} to {v['beta_high']}, N = {v['n_obs']}). In simple "
                f"words: +0.1 of hazard goes with {v['beta_tenth']} of SHDI, in the "
                "same country."
            ),
            "find4_title": "The ranking is stable (H3)",
            "find4_body": (
                f"Between the three versions of the index, the rank correlation is at "
                f"least {v['min_rho']}, and at least {v['min_top10']} of the top 10 "
                "regions are the same. Even without population, the big Indian "
                "states stay at the top: it is not only a size effect."
            ),
            "p_num": "04", "p_title": "where the risk is",
            "p_text": (
                "All ten highest-risk regions are in India, because India has both a "
                "hotter climate and a lower average SHDI. To see the differences "
                "inside France or the United States, choose a country in the "
                "dashboard. The ranking "
                "shows where to look first; it is not a verdict."
            ),
            "l_num": "05", "l_title": "the limits",
            "limit1_b": "Association, not causation.",
            "limit1": (
                "Climate, history and the economy are linked. The models show a link, "
                "not a cause."
            ),
            "limit2_b": "Six regions have no SHDI.",
            "limit2": (
                "The tests use 99 of the 105 regions; hazard still covers all 105."
            ),
            "limit3_b": "Neighbouring regions are similar.",
            "limit3": (
                "The observations are not fully independent, so the p-values are "
                "probably too small. A spatial model would be the next step."
            ),
            "limit4_b": "One development indicator.",
            "limit4": "SHDI does not show inequality inside a region.",
            "limit5_b": "Fixed thresholds.",
            "limit5": (
                "35&nbsp;&deg;C and 50&nbsp;mm are choices: France has almost zero "
                "days above 35&nbsp;&deg;C."
            ),
            "limit6_b": "Only three countries.",
            "limit6": "The results come from a pilot, not a world study.",
            "r_num": "06", "r_title": "read the full report",
            "r_text": (
                "The full report has the detailed method, all the tables, the eleven "
                "maps and the six figures."
            ),
            "read_html_kicker": "html &middot; opens in this tab",
            "read_html_title": "the full report",
            "read_pdf_kicker": "pdf &middot; print version",
            "read_pdf_title": "download the pdf",
            "sources": (
                "Tables used: outputs/tables/t01&ndash;t08. Report: "
                "outputs/report/report.html and report.pdf."
            ),
            "aside_on_page": "on this page",
            "toc_1": "01 &middot; the question",
            "toc_2": "02 &middot; how the index is built",
            "toc_3": "03 &middot; the results",
            "toc_4": "04 &middot; where the risk is",
            "toc_5": "05 &middot; the limits",
            "toc_6": "06 &middot; read the full report",
            "aside_doc": "the document",
            "aside_html": "open report.html &rarr;",
            "aside_pdf": "report.pdf &darr;",
            "aside_back": "back to the dashboard &rarr;",
            "footer_left": (
                "climate risk &amp; human development observatory &middot; pilot project"
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
    tests = pd.read_csv(tables_dir / "t05_hypothesis_tests.csv").set_index("group")
    regression = pd.read_csv(tables_dir / "t07_regression_coefficients.csv").set_index("model")
    slopes = pd.read_csv(tables_dir / "t08_country_slopes.csv").set_index("iso3")
    stability = pd.read_csv(tables_dir / "t06_rank_stability.csv")

    h1 = tests.loc["ALL"]
    pooled = regression.loc["M1 all regions"]
    within = regression.loc["M2 country effects"]
    all_row = summary.loc["ALL"]

    report_html, report_pdf = REPORT_FILES[lang]
    report_exists = (report_dir / report_html).exists()
    pdf_exists = (report_dir / report_pdf).exists()

    report_href = "/report/fr" if lang == "fr" else "/report"
    pdf_href = "/report/fr.pdf" if lang == "fr" else "/report.pdf"

    values = {
        "n_regions": f"{int(all_row['n_regions'])}",
        "population_bn": _num(all_row["population_m"] / 1000, 2, lang),
        "median_high": _num(h1["median_shdi_high_hazard"], 3, lang),
        "median_low": _num(h1["median_shdi_low_hazard"], 3, lang),
        "p_value": _p(h1["p_value"], lang),
        "rho": _num(h1["spearman_rho"], 2, lang),
        "n_obs": f"{int(within['n_obs'])}",
        "rho_ind": _num(tests.loc["IND", "spearman_rho"], 2, lang),
        "rho_usa": _num(tests.loc["USA", "spearman_rho"], 2, lang),
        "rho_fra": _num(tests.loc["FRA", "spearman_rho"], 2, lang),
        "p_fra": _num(tests.loc["FRA", "p_value"], 2, lang),
        "beta_all": _num(pooled["beta"], 2, lang),
        "beta": _num(within["beta"], 2, lang),
        "beta_low": _num(within["ci_low"], 2, lang),
        "beta_high": _num(within["ci_high"], 2, lang),
        "beta_tenth": _num(within["beta"] / 10, 3, lang),
        "slope_ind": _num(slopes.loc["IND", "slope"], 2, lang),
        "slope_usa": _num(slopes.loc["USA", "slope"], 2, lang),
        "slope_fra": _num(slopes.loc["FRA", "slope"], 2, lang),
        "min_rho": _num(stability["spearman_rho"].min(), 2, lang),
        "min_top10": f"{int(stability['same_in_top10'].min())}",
    }
    c = _copy(lang, values)

    # Hero numbers ---------------------------------------------------------
    stats = "".join([
        _stat(values["n_regions"], c["stat_regions"]),
        _stat(f'{values["population_bn"]}{" Md" if lang == "fr" else "bn"}', c["stat_people"]),
        _stat(values["rho"], c["stat_rho"]),
        _stat(values["beta"], c["stat_within"]),
    ])

    # Ticker: two identical segments so the CSS loop is seamless. ----------
    ticker_segment = (
        '<div class="ticker-seg">'
        f'<span><b>{values["n_regions"]}</b> '
        f'{"régions" if lang == "fr" else "regions"}</span>'
        f'<span><b>{len(COUNTRIES)}</b> {"pays" if lang == "fr" else "countries"}</span>'
        f'<span><b>{values["population_bn"]}{" Md" if lang == "fr" else "bn"}</b> '
        f'{"personnes" if lang == "fr" else "people"}</span>'
        f'<span><b>{values["beta"]}</b> '
        f'{"effet dans les pays" if lang == "fr" else "effect inside countries"}</span>'
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
        finding(values["rho"], c["find1_title"], c["find1_body"]),
        finding(
            f'{values["rho_ind"]} / {values["rho_usa"]} / {values["rho_fra"]}',
            c["find2_title"], c["find2_body"],
        ),
        finding(values["beta"], c["find3_title"], c["find3_body"]),
        finding(f'{values["min_top10"]}/10', c["find4_title"], c["find4_body"]),
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

    @server.route("/maps/<name>")
    def interactive_map(name: str):
        """The standalone maps, so the report can link to a real URL."""
        if name not in INTERACTIVE_MAPS:
            abort(404)
        return send_from_directory(MAPS_DIR, name)
