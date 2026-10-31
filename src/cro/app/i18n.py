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
        "exposure (population)", "exposition (population)",
    ),
    "measure.exposure.axis": ("people", "habitants"),
    "measure.exposure.low": ("fewer people", "moins d'habitants"),
    "measure.exposure.high": ("more people", "plus d'habitants"),
    "measure.exposure.rank_title": (
        "the most people", "le plus d'habitants",
    ),
    "measure.exposure.top_label": (
        "Most people", "Le plus d'habitants",
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
        "Population is coloured on a log scale. ",
        "La population est colorée sur une échelle logarithmique. ",
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
        "Hazard against development. The dotted lines are the medians; the ring "
        "is the region you selected.",
        "L'aléa face au développement. Les pointillés sont les médianes ; le "
        "cercle est la région sélectionnée.",
    ),
    "relation.caption": (
        "Each dot is one region. High SHDI is at the top, high hazard is on the "
        "right. There is one line per country: the lines go down, but much less "
        "than the big gap between India and the two other countries.",
        "Chaque point est une région. Un IDH élevé est en haut, un aléa élevé à "
        "droite. Il y a une droite par pays : elles descendent, mais beaucoup "
        "moins que le grand écart entre l'Inde et les deux autres pays.",
    ),
    "relation.finding": (
        "Spearman correlation between climate hazard and SHDI, on the 99 "
        "regions with development data.",
        "Corrélation de Spearman entre l'aléa climatique et l'IDH, sur les 99 "
        "régions qui ont des données de développement.",
    ),
    "relation.medians": ("medians", "médianes"),
    "relation.medians_text": (
        "SHDI {median_high} in the more hazardous half vs {median_low} in the "
        "other half ({p_value}).",
        "IDH {median_high} dans la moitié la plus exposée contre {median_low} "
        "dans l'autre moitié ({p_value}).",
    ),
    "relation.within": ("within", "à l'intérieur"),
    "relation.within_text": (
        "With a country effect, the regression coefficient goes from {beta_all} "
        "to {beta} (95% CI {beta_low} to {beta_high}).",
        "Avec un effet pays, le coefficient de régression passe de {beta_all} à "
        "{beta} (IC à 95 % : {beta_low} à {beta_high}).",
    ),
    "relation.by_country": ("by country", "par pays"),
    "relation.by_country_text": (
        "Spearman correlation {rho_ind} in India, {rho_usa} in the USA and "
        "{rho_fra} in France (not significant, only 13 regions).",
        "Corrélation de Spearman de {rho_ind} en Inde, {rho_usa} aux États-Unis "
        "et {rho_fra} en France (non significative, 13 régions seulement).",
    ),
    "relation.stability": ("stability", "stabilité"),
    "relation.stability_text": (
        "Across three versions of the index, at least {min_top10} of the top 10 "
        "regions stay the same (rank correlation at least {min_rho}).",
        "Entre trois versions de l'indice, au moins {min_top10} des 10 premières "
        "régions restent les mêmes (corrélation des rangs d'au moins {min_rho}).",
    ),
    "relation.axis_x": ("Climate hazard index (0-1)", "Indice d'aléa climatique (0-1)"),
    "relation.axis_y": ("Subnational HDI (SHDI)", "IDH infranational (IDH-S)"),
    "relation.trend": ("trend in the country", "tendance dans le pays"),
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
        "one-day rain and very wet days. Each one becomes a rank from 0 to 1. We "
        "average them into heat, dry and wet scores, then average the three.",
        "Six mesures climatiques issues des données quotidiennes NASA POWER "
        "(1991-2023) : jours au-dessus de 35 °C, nuits tropicales, plus longue "
        "période sèche, bilan hydrique, plus forte pluie en un jour et jours très "
        "pluvieux. Chacune devient un rang de 0 à 1. On fait la moyenne en scores "
        "chaleur, sec et humide, puis la moyenne des trois.",
    ),
    "method.exposure_title": ("02 / exposure", "02 / exposition"),
    "method.exposure_text": (
        "The number of people living in the region (GHS-POP 2020), as a rank from "
        "0 to 1. Heat is not used here because it is already in the hazard score.",
        "Le nombre d'habitants de la région (GHS-POP 2020), sous forme de rang de "
        "0 à 1. La chaleur n'est pas utilisée ici, car elle est déjà dans l'aléa.",
    ),
    "method.vulnerability_title": ("03 / vulnerability", "03 / vulnérabilité"),
    "method.vulnerability_text": (
        "1 minus the rank of the Subnational Human Development Index (Global Data "
        "Lab). Regions without SHDI have no risk score and are not in the tests.",
        "1 moins le rang de l'indice de développement humain infranational "
        "(Global Data Lab). Les régions sans IDH n'ont pas de score de risque et "
        "ne sont pas dans les tests.",
    ),
    "method.risk_title": ("04 / risk", "04 / risque"),
    "method.risk_text": (
        "Risk = hazard x exposure x vulnerability (IPCC idea). Two other versions "
        "check the ranking: a simple mean, and a version without population "
        "(hazard x vulnerability). The top regions stay almost the same.",
        "Risque = aléa × exposition × vulnérabilité (idée du GIEC). Deux autres "
        "versions vérifient le classement : une moyenne simple, et une version "
        "sans la population (aléa × vulnérabilité). Les premières régions restent "
        "presque les mêmes.",
    ),
    "method.statistics_title": ("05 / statistics", "05 / statistiques"),
    "method.statistics_text": (
        "Spearman correlation (all regions and country by country), a linear "
        "regression with and without a country effect, and a rank comparison of "
        "the three index versions. Full tables are in the report.",
        "Corrélation de Spearman (toutes les régions et pays par pays), régression "
        "linéaire avec et sans effet pays, et comparaison des rangs des trois "
        "versions de l'indice. Les tableaux complets sont dans le rapport.",
    ),
    "method.scope_title": ("06 / scope", "06 / périmètre"),
    "method.scope_text": (
        "Pilot of 105 admin-1 regions in France, India and the United States. The "
        "same code can run on more countries by changing the config file.",
        "Pilote de 105 régions admin-1 en France, en Inde et aux États-Unis. Le "
        "même code peut tourner sur d'autres pays en changeant le fichier de "
        "configuration.",
    ),
    "methods.caveat_title": (
        "Read this before quoting a number",
        "À lire avant de citer un chiffre",
    ),
    "methods.caveat_text": (
        "These are links, not causes: climate, history and the economy are mixed "
        "together. SHDI is missing for 6 of the 105 regions, so the tests use 99. "
        "Neighbouring regions look alike, so the p-values are probably too small. "
        "A big region can hide a very hot city. Use the ranking to know where to "
        "look first, not as a verdict.",
        "Ce sont des liens, pas des causes : le climat, l'histoire et l'économie "
        "sont mélangés. L'IDH manque pour 6 des 105 régions, donc les tests en "
        "utilisent 99. Les régions voisines se ressemblent, donc les p-values sont "
        "sans doute trop petites. Une grande région peut cacher une ville très "
        "chaude. Le classement dit où regarder en premier ; ce n'est pas un "
        "verdict.",
    ),

    # --- closing band ---------------------------------------------------
    "next.kicker": ("read further", "pour aller plus loin"),
    "next.title": ("the written argument.", "l'argument écrit."),
    "next.summary_title": ("two-minute summary", "synthèse en deux minutes"),
    "next.summary_meta": (
        "the question, four results, limits",
        "la question, quatre résultats, les limites",
    ),
    "next.report_title": ("full report \u2197", "rapport complet \u2197"),
    "next.report_meta": ("html \u00b7 opens in this tab", "html \u00b7 s'ouvre dans cet onglet"),
    "next.pdf_title": ("report.pdf \u2193", "rapport.pdf \u2193"),
    "next.pdf_meta": ("print layout", "mise en page imprimée"),

    # --- footer ---------------------------------------------------------
    "footer.line": (
        "climate risk & human development observatory \u00b7 pilot project",
        "observatoire du risque climatique & du développement humain \u00b7 projet pilote",
    ),
    "footer.stack": ("python \u00b7 postgis \u00b7 plotly", "python \u00b7 postgis \u00b7 plotly"),
}


def keys_missing_french() -> Iterable[str]:
    """Small self-check used by the tests."""
    return [key for key, pair in TEXTS.items() if not pair[1].strip()]
