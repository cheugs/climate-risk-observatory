"""Bilingual text for the observatory.

Every visible string lives here, in English and French, so the dashboard and
the summary page can switch language without duplicating layout code.

How the language is chosen, in order:

1. ``?lang=fr`` in the address (this is what the switch in the header links to)
2. the ``cro_lang`` cookie, so the choice follows the reader from page to page
3. English

The helpers are deliberately plain. ``t("nav.map", lang)`` returns a string;
``num`` and ``compact`` format numbers the way each language writes them
(1,234.5 in English, 1 234,5 in French).
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

LANGS = ("en", "fr")
DEFAULT_LANG = "en"
COOKIE_NAME = "cro_lang"

# French typography: a space before these marks should not break onto the
# next line. Applied automatically so the strings below stay readable.
_FR_TIGHT = (
    (" :", "\u00a0:"),
    (" ;", "\u00a0;"),
    (" ?", "\u00a0?"),
    (" !", "\u00a0!"),
    ("« ", "«\u00a0"),
    (" »", "\u00a0»"),
    (" %", "\u00a0%"),
)


def normalize(value: object) -> str:
    """Map anything that looks like a language tag to ``en`` or ``fr``."""
    text = str(value or "").strip().lower()
    if text.startswith("fr"):
        return "fr"
    return DEFAULT_LANG


def current_lang() -> str:
    """The language of the request being served.

    Outside a request (tests, the report builder) this is English.
    """
    from flask import has_request_context, request

    if not has_request_context():
        return DEFAULT_LANG
    return normalize(
        request.args.get("lang") or request.cookies.get(COOKIE_NAME) or DEFAULT_LANG
    )


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Return one string in the requested language."""
    english, french = TEXTS[key]
    text = french if normalize(lang) == "fr" else english
    if normalize(lang) == "fr":
        for plain, tight in _FR_TIGHT:
            text = text.replace(plain, tight)
    return text


def tf(key: str, lang: str = DEFAULT_LANG, **values) -> str:
    """Return one string with ``{placeholders}`` filled in."""
    return t(key, lang).format(**values)


def num(value, digits: int = 2, lang: str = DEFAULT_LANG) -> str:
    """A number with a real minus sign and the right decimal separator."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return t("misc.na", lang)
    text = f"{float(value):,.{digits}f}"
    if normalize(lang) == "fr":
        text = text.replace(",", "\u202f").replace(".", ",")
    return text.replace("-", "\u2212")


def compact(value, lang: str = DEFAULT_LANG) -> str:
    """Turn 1,803,100,000 into 1.80bn (English) or 1,80 Md (French)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return t("misc.na", lang)
    value = float(value)
    french = normalize(lang) == "fr"
    if value >= 1e9:
        scaled, unit = value / 1e9, ("Md" if french else "bn")
        number = f"{scaled:.2f}"
    elif value >= 1e6:
        scaled, unit = value / 1e6, ("M" if french else "m")
        number = f"{scaled:.1f}"
    elif value >= 1e3:
        scaled, unit = value / 1e3, "k"
        number = f"{scaled:.1f}"
    else:
        number, unit = f"{value:,.0f}", ""
    if french:
        number = number.replace(",", "\u202f").replace(".", ",")
    return f"{number} {unit}".strip()


def plural(count: float, singular: str, plural_form: str, lang: str) -> str:
    return singular if abs(float(count) - 1) < 1e-9 else plural_form


# ---------------------------------------------------------------------------
# The text itself: key -> (English, French)
# ---------------------------------------------------------------------------

TEXTS: dict[str, tuple[str, str]] = {
    # --- shared ---------------------------------------------------------
    "misc.na": ("n/a", "n.d."),
    "misc.en": ("en", "en"),
    "misc.fr": ("fr", "fr"),
    "misc.and": (" and ", " et "),
    "misc.language": ("language", "langue"),
    "misc.english": ("English", "anglais"),
    "misc.french": ("French", "français"),

    # --- top navigation -------------------------------------------------
    "nav.map": ("map", "carte"),
    "nav.ranking": ("ranking", "classement"),
    "nav.relationship": ("relationship", "relation"),
    "nav.profile": ("profile", "profil"),
    "nav.methods": ("methods", "méthode"),
    "nav.summary": ("summary", "synthèse"),
    "nav.dashboard": ("dashboard", "tableau de bord"),
    "nav.report": ("full report", "rapport complet"),

    # --- header ticker --------------------------------------------------
    "ticker.regions": ("admin-1 regions", "régions admin-1"),
    "ticker.countries": ("countries", "pays"),
    "ticker.people": ("people covered", "personnes couvertes"),
    "ticker.median_risk": ("median risk", "risque médian"),
    "ticker.rho": ("hazard-SHDI rank correlation", "corrélation aléa-IDH"),
    "ticker.top_region": ("highest risk region", "région la plus à risque"),

    # --- hero -----------------------------------------------------------
    "hero.eyebrow": (
        "climate risk & human development observatory",
        "observatoire du risque climatique & du développement humain",
    ),
    "hero.scope": (
        "pilot \u00b7 france / india / united states",
        "pilote \u00b7 france / inde / états-unis",
    ),
    "hero.title_a": ("where climate stress", "là où le stress climatique"),
    "hero.title_b": ("meets low development.", "rencontre le faible développement."),
    "hero.lede_a": (
        "A regional observatory built from NASA climate records, population "
        "grids and subnational development data. Every region is scored for ",
        "Un observatoire régional construit à partir des relevés climatiques de "
        "la NASA, des grilles de population et de données infranationales de "
        "développement. Chaque région est notée selon son ",
    ),
    "hero.lede_b": (
        ", then set against its level of human development. Click a map to "
        "inspect a place.",
        ", puis confrontée à son niveau de développement humain. Cliquez sur "
        "une carte pour examiner un lieu.",
    ),
    "hero.summary_link": (
        "read the two-minute summary ",
        "lire la synthèse en deux minutes ",
    ),
    "stat.regions": ("admin-1 regions", "régions admin-1"),
    "stat.countries": ("countries in the pilot", "pays du pilote"),
    "stat.people": ("people covered", "personnes couvertes"),
    "stat.rho": ("hazard-SHDI rank correlation", "corrélation aléa-IDH"),

    # --- controls -------------------------------------------------------
    "controls.view": ("view by country", "vue par pays"),
    "controls.measure": ("measure shown on the map", "indicateur affiché sur la carte"),
    "controls.find": ("find a region", "trouver une région"),
    "controls.search": ("search a region", "rechercher une région"),
    "country.all": ("all", "tout"),
    "country.FRA": ("france", "france"),
    "country.IND": ("india", "inde"),
    "country.USA": ("usa", "états-unis"),
    "country.name.FRA": ("France", "France"),
    "country.name.IND": ("India", "Inde"),
    "country.name.USA": ("United States", "États-Unis"),
    "hover.population": ("Population", "Population"),
    "hover.hazard": ("Hazard", "Aléa"),
    "hover.shdi": ("SHDI", "IDH"),
    "hover.risk": ("Risk", "Risque"),

    # --- measures -------------------------------------------------------
    "measure.risk.chip": ("risk", "risque"),
    "measure.risk.label": ("composite risk", "risque composite"),
    "measure.risk.axis": ("risk index", "indice de risque"),
    "measure.risk.low": ("less risk", "moins de risque"),
    "measure.risk.high": ("more risk", "plus de risque"),
    "measure.risk.rank_title": (
        "the highest composite risk", "le risque composite le plus élevé",
    ),
    "measure.risk.top_label": (
        "Highest composite risk", "Risque composite le plus élevé",
    ),

    "measure.hazard.chip": ("hazard", "aléa"),
    "measure.hazard.label": ("climate hazard", "aléa climatique"),
    "measure.hazard.axis": ("hazard index", "indice d'aléa"),
    "measure.hazard.low": ("lower hazard", "aléa plus faible"),
    "measure.hazard.high": ("higher hazard", "aléa plus élevé"),
    "measure.hazard.rank_title": (
        "the highest climate hazard", "l'aléa climatique le plus élevé",
    ),
    "measure.hazard.top_label": (
        "Highest climate hazard", "Aléa climatique le plus élevé",
    ),

    "measure.heat.chip": ("heat days", "jours de chaleur"),
    "measure.heat.label": ("heat days above 35 C", "jours de chaleur au-dessus de 35 °C"),
    "measure.heat.axis": ("days per year", "jours par an"),
    "measure.heat.low": ("fewer hot days", "moins de jours chauds"),
    "measure.heat.high": ("more hot days", "plus de jours chauds"),
    "measure.heat.rank_title": (
        "the most days above 35 C", "le plus de jours au-dessus de 35 °C",
    ),
    "measure.heat.top_label": (
        "Most days above 35 C", "Plus de jours au-dessus de 35 °C",
    ),

    "measure.exposure.chip": ("exposure", "exposition"),
    "measure.exposure.label": (
        "exposure to extreme heat", "exposition à la chaleur extrême",
    ),
    "measure.exposure.axis": ("person-days of heat", "jours-personnes de chaleur"),
    "measure.exposure.low": ("lower exposure", "exposition plus faible"),
    "measure.exposure.high": ("higher exposure", "exposition plus forte"),
    "measure.exposure.rank_title": (
        "the largest heat exposure", "la plus forte exposition à la chaleur",
    ),
    "measure.exposure.top_label": (
        "Largest heat exposure", "Plus forte exposition à la chaleur",
    ),

    "measure.vulnerability.chip": ("vulnerability", "vulnérabilité"),
    "measure.vulnerability.label": ("vulnerability", "vulnérabilité"),
    "measure.vulnerability.axis": ("vulnerability index", "indice de vulnérabilité"),
    "measure.vulnerability.low": ("less vulnerable", "moins vulnérable"),
    "measure.vulnerability.high": ("more vulnerable", "plus vulnérable"),
    "measure.vulnerability.rank_title": (
        "the highest vulnerability", "la plus forte vulnérabilité",
    ),
    "measure.vulnerability.top_label": (
        "Highest vulnerability", "Vulnérabilité la plus forte",
    ),

    "measure.shdi.chip": ("SHDI", "IDH"),
    "measure.shdi.label": ("human development (SHDI)", "développement humain (IDH-S)"),
    "measure.shdi.axis": ("SHDI", "IDH-S"),
    "measure.shdi.low": ("lower SHDI", "IDH-S plus faible"),
    "measure.shdi.high": ("higher SHDI", "IDH-S plus élevé"),
    "measure.shdi.rank_title": (
        "the lowest human development", "le développement humain le plus faible",
    ),
    "measure.shdi.top_label": ("Lowest SHDI", "IDH-S le plus faible"),

    # --- map section ----------------------------------------------------
    "map.title": ("the map.", "la carte."),
    "map.desc": (
        "Three countries, one shared colour scale when they are shown "
        "together. Pick a country above to enlarge its map and see internal "
        "differences.",
        "Trois pays, une échelle de couleur commune lorsqu'ils sont affichés "
        "ensemble. Choisissez un pays ci-dessus pour agrandir sa carte et voir "
        "les différences internes.",
    ),
    "map.region_count": ("{n} regions", "{n} régions"),
    "map.legend_colour": ("colour = {label}", "couleur = {label}"),
    "map.legend_shared": (
        "shared across the three maps", "commune aux trois cartes",
    ),
    "map.legend_scaled": ("scaled to {country} only", "ajustée à {country} uniquement"),
    "map.note_top": ("{label}: {region} ({value}). ", "{label} : {region} ({value}). "),
    "map.note_click": (
        "Click any region to open its profile. ",
        "Cliquez sur une région pour ouvrir son profil. ",
    ),
    "map.note_shared": (
        "The colour scale is shared by all three maps, so shades compare across "
        "countries. India sets the top of the scale, which is why France and the "
        "United States look pale here; choose a country to rescale it. ",
        "L'échelle de couleur est commune aux trois cartes, les nuances sont donc "
        "comparables d'un pays à l'autre. L'Inde fixe le haut de l'échelle, ce qui "
        "explique la pâleur de la France et des États-Unis ; choisissez un pays "
        "pour la recalibrer. ",
    ),
    "map.note_fitted": (
        "The colour scale is fitted to this country, so it shows internal "
        "differences. ",
        "L'échelle de couleur est ajustée à ce pays : elle montre les différences "
        "internes. ",
    ),
    "map.note_log": (
        "Exposure is coloured on a log scale. ",
        "L'exposition est colorée sur une échelle logarithmique. ",
    ),
    "map.note_us": (
        "The US panel shows the continental states; Alaska, Hawai\u02bbi and the "
        "territories remain in the ranking and profile data.",
        "Le panneau américain montre les États contigus ; l'Alaska, Hawaï et les "
        "territoires restent dans le classement et les profils.",
    ),

    # --- ranking --------------------------------------------------------
    "ranking.title": ("the ranking.", "le classement."),
    "ranking.desc_a": ("The ten regions with ", "Les dix régions avec "),
    "ranking.desc_b": (
        ". Click a row to load it in the profile at the bottom of the page.",
        ". Cliquez sur une ligne pour l'afficher dans le profil en bas de page.",
    ),
    "ranking.tooltip": ("Show {region} in the profile", "Afficher {region} dans le profil"),

    # --- relationship ---------------------------------------------------
    "relation.title": ("the relationship.", "la relation."),
    "relation.desc": (
        "Hazard against development. The dashed lines mark the study medians; "
        "the ring marks the region you selected.",
        "L'aléa face au développement. Les pointillés marquent les médianes de "
        "l'étude ; le cercle désigne la région sélectionnée.",
    ),
    "relation.caption": (
        "Each dot is one admin-1 region. High SHDI sits high on the y-axis; high "
        "hazard sits to the right. The pattern runs downward: more hazard, less "
        "development.",
        "Chaque point est une région admin-1. Un IDH élevé se situe haut sur l'axe "
        "vertical, un aléa élevé à droite. La tendance descend : plus d'aléa, "
        "moins de développement.",
    ),
    "relation.finding": (
        "Spearman rank correlation between climate hazard and SHDI, across the "
        "99 regions with development data.",
        "Corrélation de rang de Spearman entre l'aléa climatique et l'IDH, sur les "
        "99 régions disposant de données de développement.",
    ),
    "relation.medians": ("medians", "médianes"),
    "relation.medians_text": (
        "SHDI 0.786 in high-hazard regions vs 0.936 in low-hazard regions "
        "(Mann-Whitney p = 1.4e-06).",
        "IDH 0,786 dans les régions à fort aléa contre 0,936 dans celles à faible "
        "aléa (Mann-Whitney p = 1,4e-06).",
    ),
    "relation.within": ("within", "à l'intérieur"),
    "relation.within_text": (
        "A one-SD rise in hazard goes with -0.21 SD of SHDI inside countries "
        "(95% CI -0.32 to -0.11).",
        "Une hausse d'un écart-type de l'aléa correspond à −0,21 écart-type d'IDH "
        "à l'intérieur des pays (IC à 95 % : −0,32 à −0,11).",
    ),
    "relation.by_country": ("by country", "par pays"),
    "relation.by_country_text": (
        "Slope -0.22 in India, -0.14 in the USA and +0.01 in France, where hazard "
        "range is narrow.",
        "Pente de −0,22 en Inde, −0,14 aux États-Unis et +0,01 en France, où la "
        "plage d'aléa est étroite.",
    ),
    "relation.concentration": ("concentration", "concentration"),
    "relation.concentration_text": (
        "The top 10% most hazardous regions hold 1.38x their population share of "
        "person-days of heat.",
        "Les 10 % de régions les plus exposées à l'aléa concentrent 1,38 fois leur "
        "part de population en jours-personnes de chaleur.",
    ),
    "relation.axis_x": ("Climate hazard index (0-1)", "Indice d'aléa climatique (0-1)"),
    "relation.axis_y": ("Subnational HDI (SHDI)", "IDH infranational (IDH-S)"),
    "relation.trend": ("trend (LOWESS)", "tendance (LOWESS)"),
    "relation.selected": ("selected", "sélection"),
    "relation.empty": (
        "No development data for this view.",
        "Aucune donnée de développement pour cette vue.",
    ),
    "relation.hover": (
        "<b>{region}</b><br>Hazard {hazard:.3f}<br>SHDI {shdi:.3f}<br>"
        "Risk {risk} \u00b7 population {population}",
        "<b>{region}</b><br>Aléa {hazard:.3f}<br>IDH {shdi:.3f}<br>"
        "Risque {risk} \u00b7 population {population}",
    ),

    # --- profile --------------------------------------------------------
    "profile.title": ("one place.", "un lieu."),
    "profile.desc": (
        "The chosen region in absolute numbers, and where it sits in the "
        "distribution. The diamond is its country median.",
        "La région choisie en chiffres absolus, et sa position dans la "
        "distribution. Le losange est la médiane de son pays.",
    ),
    "profile.caption": (
        "Bars show percentile position among the pilot regions that have data "
        "for that measure, from 0 (lowest) to 100 (highest). The dotted line is "
        "the study median, the diamond is the country median. Hover to read the "
        "raw values.",
        "Les barres indiquent la position en centile parmi les régions du pilote "
        "disposant de données pour cet indicateur, de 0 (plus bas) à 100 (plus "
        "haut). La ligne pointillée est la médiane de l'étude, le losange la "
        "médiane du pays. Survolez pour lire les valeurs brutes.",
    ),
    "profile.axis": (
        "percentile among regions with data", "centile parmi les régions avec données",
    ),
    "profile.this_region": ("this region", "cette région"),
    "profile.country_median": ("country median", "médiane du pays"),
    "profile.percentile": ("{value}e centile", "{value}e centile"),
    "profile.percentile_en": ("{value}th percentile", "{value}e centile"),
    "profile.empty": (
        "Choose a region to see its profile.",
        "Choisissez une région pour voir son profil.",
    ),
    "profile.choose": (
        "Choose a region above, or click one on the map.",
        "Choisissez une région ci-dessus, ou cliquez-en une sur la carte.",
    ),
    "profile.not_found": ("Region not found.", "Région introuvable."),
    "detail.risk_rank": ("risk rank", "rang du risque"),
    "detail.risk_index": ("risk index", "indice de risque"),
    "detail.hazard_index": ("hazard index", "indice d'aléa"),
    "detail.heat_days": ("heat days / year", "jours de chaleur / an"),
    "detail.population": ("population", "population"),
    "detail.shdi": ("SHDI", "IDH"),
    "detail.vulnerability": ("vulnerability", "vulnérabilité"),
    "detail.heat_exposure": ("heat exposure", "exposition à la chaleur"),
    "detail.of_ranked": (" of {n}", " sur {n}"),
    "detail.person_days": (" person-days", " jours-personnes"),
    "metric.risk": ("Risk", "Risque"),
    "metric.vulnerability": ("Vulnerability", "Vulnérabilité"),
    "metric.hazard": ("Hazard", "Aléa"),
    "metric.exposure": ("Exposure", "Exposition"),
    "metric.heat": ("Heat days", "Jours de chaleur"),
    "metric.shdi": ("SHDI", "IDH"),

    # --- methods --------------------------------------------------------
    "methods.title": ("methods & data.", "méthode & données."),
    "methods.desc": (
        "How the index is built, and the limits of what it can say. The full "
        "statistical report is in the repository.",
        "Comment l'indice est construit, et les limites de ce qu'il peut dire. "
        "Le rapport statistique complet est dans le dépôt.",
    ),
    "method.hazard_title": ("01 / hazard", "01 / aléa"),
    "method.hazard_text": (
        "Six climate measures from NASA POWER daily data (1991-2023): days above "
        "35 C, tropical nights, the longest dry spell, water balance, the heaviest "
        "one-day rainfall and very wet days. Each is converted to a percentile, "
        "combined into heat, dry and wet sub-indices, then averaged.",
        "Six mesures climatiques issues des données quotidiennes NASA POWER "
        "(1991-2023) : jours au-dessus de 35 °C, nuits tropicales, plus longue "
        "séquence sèche, bilan hydrique, plus forte pluie en un jour et jours très "
        "humides. Chacune est convertie en centile, combinée en sous-indices "
        "chaleur, sécheresse et humidité, puis moyennée.",
    ),
    "method.exposure_title": ("02 / exposure", "02 / exposition"),
    "method.exposure_text": (
        "GHS-POP 2020 population at 30 arc-seconds. Each person is assigned to the "
        "nearest climate sample point, so person-days of extreme heat = population "
        "x heat days. This is why a hot but empty region does not rank like a hot "
        "and crowded one.",
        "Population GHS-POP 2020 à 30 secondes d'arc. Chaque personne est rattachée "
        "au point climatique le plus proche, si bien que les jours-personnes de "
        "chaleur extrême = population × jours de chaleur. C'est pourquoi une région "
        "chaude mais vide ne se classe pas comme une région chaude et dense.",
    ),
    "method.vulnerability_title": ("03 / vulnerability", "03 / vulnérabilité"),
    "method.vulnerability_text": (
        "One minus the percentile rank of the subnational Human Development Index "
        "(Global Data Lab). Regions without an SHDI keep their hazard and exposure "
        "scores but are left out of the development models.",
        "Un moins le rang centile de l'indice de développement humain "
        "infranational (Global Data Lab). Les régions sans IDH conservent leurs "
        "scores d'aléa et d'exposition mais sont exclues des modèles de "
        "développement.",
    ),
    "method.risk_title": ("04 / risk", "04 / risque"),
    "method.risk_text": (
        "Composite risk = hazard x exposure x vulnerability, following the IPCC "
        "framing. An additive version and a PCA-weighted version are kept as "
        "robustness checks; the regional ordering barely moves between them.",
        "Risque composite = aléa × exposition × vulnérabilité, selon le cadre du "
        "GIEC. Une version additive et une version pondérée par ACP sont "
        "conservées comme tests de robustesse ; l'ordre des régions change à "
        "peine d'une version à l'autre.",
    ),
    "method.statistics_title": ("05 / statistics", "05 / statistiques"),
    "method.statistics_text": (
        "Mann-Whitney tests, Cliff's delta and Spearman correlation for the "
        "development relationship; country fixed effects for the regression; "
        "Moran's I and LISA for spatial clustering. Full tables are in the report.",
        "Tests de Mann-Whitney, delta de Cliff et corrélation de Spearman pour la "
        "relation avec le développement ; effets fixes pays pour la régression ; "
        "I de Moran et LISA pour l'agrégation spatiale. Les tableaux complets sont "
        "dans le rapport.",
    ),
    "method.scope_title": ("06 / scope", "06 / périmètre"),
    "method.scope_text": (
        "Pilot of 105 admin-1 regions in France, India and the United States. The "
        "pipeline is written to scale to roughly 3,700 regions worldwide without "
        "changing the index definition.",
        "Pilote de 105 régions admin-1 en France, en Inde et aux États-Unis. Le "
        "pipeline est écrit pour passer à environ 3 700 régions dans le monde sans "
        "changer la définition de l'indice.",
    ),
    "methods.caveat_title": (
        "Read this before quoting a number",
        "À lire avant de citer un chiffre",
    ),
    "methods.caveat_text": (
        "These are associations, not causal effects. Climate, history, "
        "institutions and geography are entangled, and this pilot cannot separate "
        "them. Development data are missing for 6 of the 105 regions, so "
        "development tests use 99. Boundaries are ADM1 units, not lived "
        "neighbourhoods; a large region can hide a hot city. Use the ranking as a "
        "screening tool, not a verdict.",
        "Ce sont des associations, pas des effets causaux. Climat, histoire, "
        "institutions et géographie sont enchevêtrés, et ce pilote ne peut pas les "
        "séparer. Les données de développement manquent pour 6 des 105 régions : "
        "les tests de développement portent donc sur 99 régions. Les limites sont "
        "des unités ADM1, pas des quartiers vécus ; une grande région peut cacher "
        "une ville surchauffée. Utilisez le classement comme un outil de "
        "repérage, pas comme un verdict.",
    ),

    # --- closing band ---------------------------------------------------
    "next.kicker": ("read further", "pour aller plus loin"),
    "next.title": ("the written argument.", "l'argument écrit."),
    "next.summary_title": ("two-minute summary", "synthèse en deux minutes"),
    "next.summary_meta": (
        "the question, four findings, limits",
        "la question, quatre constats, les limites",
    ),
    "next.report_title": ("full report \u2197", "rapport complet \u2197"),
    "next.report_meta": ("html \u00b7 opens in this tab", "html \u00b7 s'ouvre dans cet onglet"),
    "next.pdf_title": ("report.pdf \u2193", "rapport.pdf \u2193"),
    "next.pdf_meta": ("print layout", "mise en page imprimée"),

    # --- footer ---------------------------------------------------------
    "footer.line": (
        "climate risk & human development observatory \u00b7 pilot edition",
        "observatoire du risque climatique & du développement humain \u00b7 édition pilote",
    ),
    "footer.stack": ("python \u00b7 postgis \u00b7 plotly", "python \u00b7 postgis \u00b7 plotly"),
}


def keys_missing_french() -> Iterable[str]:
    """Small self-check used by the tests."""
    return [key for key, pair in TEXTS.items() if not pair[1].strip()]
