"""Build the report.

The prose lives in `report/report.qmd` for English and `report/report.fr.qmd`
for French. This script does three things:

1. writes small Markdown snippets (tables and key numbers) from the CSV and
   Parquet files the analysis produced, once for each language,
2. renders both reports with Quarto if Quarto is installed,
3. otherwise falls back to a plain HTML build using the `markdown` package,
   so the English report can still be produced on a machine without Quarto.

Why snippets instead of writing the numbers into the text by hand: if the
data are refreshed, the tables must change too. Copy-pasted numbers go stale
silently - this way they cannot.

Run it with:  cro report
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

from cro.config import PROJECT_ROOT, load_config
from cro.utils import log

REPORT_DIR = PROJECT_ROOT / "report"
GENERATED_DIR = REPORT_DIR / "generated"
GENERATED_FR = REPORT_DIR / "generated_fr"
QMD_PATH = REPORT_DIR / "report.qmd"
QMD_FR_PATH = REPORT_DIR / "report.fr.qmd"


# ---------------------------------------------------------------------------
# French labels for the generated tables
# ---------------------------------------------------------------------------

FRENCH_COLUMNS = {
    "Country": "Pays",
    "Regions": "Régions",
    "Population (m)": "Population (M)",
    "Hazard (mean)": "Aléa (moyenne)",
    "Exposure (mean)": "Exposition (moyenne)",
    "Vulnerability (mean)": "Vulnérabilité (moyenne)",
    "Risk (median)": "Risque (médiane)",
    "Person-days of heat (bn/yr)": "Jours-personnes de chaleur (Md/an)",
    "Indicator": "Indicateur",
    "Region": "Région",
    "Hazard": "Aléa",
    "Exposure": "Exposition",
    "Vulnerability": "Vulnérabilité",
    "Risk": "Risque",
    "Test": "Test",
    "Estimate": "Estimation",
    "95% CI": "IC à 95 %",
    "p-value": "p-valeur",
    "Version A": "Version A",
    "Version B": "Version B",
    "Spearman rho": "Rho de Spearman",
    "Model": "Modèle",
    "Variable": "Variable",
    "Beta (95% CI)": "Bêta (IC à 95 %)",
    "Sig.": "Seuil",
    "N": "N",
    "R squared": "R²",
    "Slope (95% CI)": "Pente (IC à 95 %)",
    "Moran's I": "I de Moran",
    "p (simulated)": "p (simulée)",
    "People (m)": "Population (M)",
}

FRENCH_VALUES = {
    "Country": {
        "ALL": "Tous",
    },
    "Model": {
        "M1 pooled": "M1 groupé",
        "M2 controls": "M2 contrôles",
        "M3 country FE": "M3 effets fixes pays",
        "M4 components": "M4 composantes",
    },
    "Variable": {
        "hazard_equal_z": "aléa (z)",
        "hazard_heat_z": "aléa chaleur (z)",
        "hazard_dry_z": "aléa sécheresse (z)",
        "hazard_wet_z": "aléa humidité (z)",
        "abs_lat_z": "|latitude| (z)",
        "log_density_z": "log(densité) (z)",
        "remote": "éloignement",
        "risk_equal": "risque composite",
        "hazard_equal": "aléa",
        "shdi": "IDH-S",
    },
    "Test": {
        "H1 Concentration ratio": "H1 Ratio de concentration",
        "H1 Share of person-days, top 10%": "H1 Part des jours-personnes, 10 % supérieurs",
        "H1 Share of population, top 10%": "H1 Part de la population, 10 % supérieurs",
        "H2 Median SHDI, high hazard": "H2 IDH-S médian, aléa élevé",
        "H2 Median SHDI, low hazard": "H2 IDH-S médian, aléa faible",
        "H2 Mann-Whitney p": "H2 p de Mann-Whitney",
        "H2 Cliff's delta": "H2 delta de Cliff",
        "H2 Spearman rho": "H2 rho de Spearman",
        "H2 Spearman p": "H2 p de Spearman",
    },
}

FRENCH_CAPTIONS = {
    "Table 1. Summary by country.": "Tableau 1. Synthèse par pays.",
    "Table 2. Mean climate indicators by country, 2004-2023.":
        "Tableau 2. Indicateurs climatiques moyens par pays, 2004-2023.",
    "Table 3. The ten highest-risk regions.": "Tableau 3. Les dix régions les plus à risque.",
    "Table 4. Hypothesis tests H1 and H2.": "Tableau 4. Tests d'hypothèses H1 et H2.",
    "Table 5. Agreement between index versions.":
        "Tableau 5. Concordance entre les versions de l'indice.",
    "Table 6. Regression coefficients (standardised).":
        "Tableau 6. Coefficients de régression (standardisés).",
    "Table 7. Within-country slope of SHDI on hazard.":
        "Tableau 7. Pente intra-pays de l'IDH-S sur l'aléa.",
    "Table 8. Moran's I by country (Queen contiguity).":
        "Tableau 8. I de Moran par pays (contiguïté reine).",
}


def _fr_number(value: float, digits: int = 3) -> str:
    """Format a float the French way: 1 803,072."""
    text = f"{value:,.{digits}f}"
    text = text.replace(",", "\u202f").replace(".", ",")
    return text.replace("-", "\u2212")


def _french_validation(text: str) -> str:
    """Translate the fixed wording of the validation summary.

    The check *names* are stable strings in `cro/validate.py`; translating
    them here keeps that module English-only (it is a developer tool) while
    the French report still reads in French.
    """
    import re

    replacements = [
        ("# Data checks", "# Contrôles des données"),
        ("Checks run:", "Contrôles exécutés :"),
        ("Passed:", "Réussis :"),
        ("Failed:", "Échoués :"),
        ("climate sample points", "points d'échantillonnage climatiques"),
        ("population reconciles", "population conciliée"),
        ("climate ranges", "plages climatiques"),
        ("index bounds", "bornes des indices"),
        ("master table", "table maîtresse"),
        ("development coverage", "couverture du développement"),
        ("output tables", "tableaux de sortie"),
        ("boundaries", "limites administratives"),
        (" region total ", " total régional "),
        (" point total ", " total par points "),
        ("% difference", "% d'écart"),
        ("points covering", "points couvrant"),
        ("all index columns within 0..1", "toutes les colonnes d'indice comprises entre 0 et 1"),
        ("rows, 0 duplicates, 0 regions missing", "lignes, 0 doublon, 0 région manquante"),
        ("SHDI available for", "IDH-S disponible pour"),
        ("regions", "régions"),
        ("countries", "pays"),
        ("checked", "vérifiées"),
        ("tables present", "tableaux présents"),
    ]
    for plain, french in replacements:
        text = text.replace(plain, french)

    # 1,803.1M -> 1 803,1 M, and 0.1% -> 0,1 %.
    text = re.sub(
        r"(\d),(\d{3})\.(\d)M",
        lambda match: f"{match.group(1)} {match.group(2)},{match.group(3)} M",
        text,
    )
    text = re.sub(r"(\d)\.(\d)%", r"\1,\2 %", text)
    text = re.sub(r"(\d)%", r"\1 %", text)
    return text


def _fmt(value, digits: int = 2, lang: str = "en") -> str:
    """One number, written the way the chosen language writes numbers."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n.d." if lang == "fr" else "n/a"
    if lang == "fr":
        return _fr_number(float(value), digits)
    return f"{float(value):.{digits}f}"


def _pct(value, digits: int = 1, lang: str = "en") -> str:
    """A share: '12.3%' in English, '12,3 %' in French."""
    text = _fmt(value * 100, digits, lang)
    return f"{text}\u00a0%" if lang == "fr" else f"{text}%"


def _sci(value, lang: str = "en") -> str:
    """A small p-value without fake precision."""
    text = f"{value:.2g}"
    return text.replace(".", ",") if lang == "fr" else text


def _interval(low: float, high: float, lang: str, digits: int = 3) -> str:
    """'1.21 to 1.75' in English, '1,21 à 1,75' in French."""
    if lang == "fr":
        return f"{_fr_number(low, digits)} à {_fr_number(high, digits)}"
    return f"{low:.{digits}f} to {high:.{digits}f}"


def _localise(table: pd.DataFrame, caption: str, lang: str) -> tuple[pd.DataFrame, str]:
    """Translate the headers, the coded values and the caption of a table."""
    if lang != "fr":
        return table, caption
    table = table.rename(columns=FRENCH_COLUMNS)
    for column, mapping in FRENCH_VALUES.items():
        if column in table.columns:
            table[column] = table[column].replace(mapping)
        french_column = FRENCH_COLUMNS.get(column, column)
        if french_column in table.columns:
            table[french_column] = table[french_column].replace(mapping)
    return table, FRENCH_CAPTIONS.get(caption, caption)


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------

def _markdown_table(df: pd.DataFrame, caption: str, lang: str = "en") -> str:
    """Turn a DataFrame into a Markdown table with a bold caption."""
    df, caption = _localise(df.copy(), caption, lang)
    if lang == "fr":
        for column in df.columns:
            if pd.api.types.is_float_dtype(df[column]):
                df[column] = df[column].map(lambda value: _fr_number(value))
    table = df.to_markdown(index=False, floatfmt=".3f", tablefmt="pipe")
    return f"**{caption}**\n\n{table}\n"


def _read_table(name: str) -> pd.DataFrame:
    """Read one of the analysis CSVs (they are small and human-readable)."""
    cfg = load_config()
    path = Path(cfg["paths"]["outputs"]) / "tables" / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_processed(name: str) -> pd.DataFrame:
    cfg = load_config()
    path = Path(cfg["paths"]["processed"]) / name
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


# ---------------------------------------------------------------------------
# 1. Build the snippets
# ---------------------------------------------------------------------------

def write_summary_snippet(lang: str = "en") -> None:
    """The key-numbers block that appears in the executive summary.

    It is generated from `key_numbers.json` so the printed values and the
    computed values can never disagree. The French version is written to
    `generated_fr/`, which is where `report.fr.qmd` looks for its includes.
    """
    cfg = load_config()
    key_path = Path(cfg["paths"]["processed"]) / "key_numbers.json"
    if not key_path.exists():
        log("report: key_numbers.json missing, skipping summary block")
        return

    with open(key_path, "r", encoding="utf-8") as f:
        key = json.load(f)

    h3 = key.get("h3_country_fe_beta") or {}
    if lang == "fr":
        population = _fmt(key["population_millions"] / 1000, 2, lang)
        unit = "milliard" if abs(key["population_millions"] / 1000) < 2 else "milliards"
        lines = [
            "::: {.callout-note}",
            "**Les chiffres clés en un coup d'œil**",
            "",
            f"- **{key['n_regions']}** régions admin-1 dans **{key['n_countries']}** pays, "
            f"couvrant **{population} {unit}** de personnes.",
            f"- Données de développement disponibles pour "
            f"**{key['regions_with_development']}** d'entre elles.",
            f"- Ratio de concentration (H1) : **{_fmt(key['h1_concentration_ratio'], 2, lang)}** "
            f"(IC à 95\u00a0% : {_fmt(key['h1_ci'][0], 2, lang)} à "
            f"{_fmt(key['h1_ci'][1], 2, lang)}).",
            f"- IDH-S médian, aléa élevé contre aléa faible (H2) : "
            f"**{_fmt(key['h2_median_shdi_high_hazard'], 3, lang)}** contre "
            f"**{_fmt(key['h2_median_shdi_low_hazard'], 3, lang)}**, "
            f"p = {_sci(key['h2_p_value'], lang)}.",
        ]
        if h3:
            lines.append(
                f"- Coefficient d'aléa intra-pays (H3) : **{_fmt(h3['beta'], 2, lang)}** "
                f"(IC à 95\u00a0% : {_fmt(h3['ci'][0], 2, lang)} à "
                f"{_fmt(h3['ci'][1], 2, lang)}, N = {h3['n']})."
            )
        lines += [":::", ""]
        out_dir = GENERATED_FR
    else:
        lines = [
            "::: {.callout-note}",
            "**Key numbers at a glance**",
            "",
            f"- **{key['n_regions']}** admin-1 regions in **{key['n_countries']}** countries, "
            f"covering **{key['population_millions']:.1f} million** people.",
            f"- Development data available for **{key['regions_with_development']}** of them.",
            f"- Concentration ratio (H1): **{key['h1_concentration_ratio']:.2f}** "
            f"(95% CI {key['h1_ci'][0]:.2f}-{key['h1_ci'][1]:.2f}).",
            f"- Median SHDI, high vs low hazard (H2): **{key['h2_median_shdi_high_hazard']:.3f}** "
            f"vs **{key['h2_median_shdi_low_hazard']:.3f}**, p = {key['h2_p_value']:.2g}.",
        ]
        if h3:
            lines.append(
                f"- Within-country hazard coefficient (H3): **{h3['beta']:.2f}** "
                f"(95% CI {h3['ci'][0]:.2f} to {h3['ci'][1]:.2f}, N = {h3['n']})."
            )
        lines += [":::", ""]
        out_dir = GENERATED_DIR

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_table_snippets(lang: str = "en") -> None:
    """One snippet per table used in the report."""
    out_dir = GENERATED_FR if lang == "fr" else GENERATED_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Table 1: summary by country -------------------------------------
    summary = _read_table("t01_summary_by_country.csv")
    if not summary.empty:
        table = summary.rename(columns={
            "group": "Country", "n_regions": "Regions",
            "population_m": "Population (m)", "hazard_mean": "Hazard (mean)",
            "exposure_mean": "Exposure (mean)", "vulnerability_mean": "Vulnerability (mean)",
            "risk_median": "Risk (median)",
            "person_days_heat_bn": "Person-days of heat (bn/yr)",
        })
        (out_dir / "t01.md").write_text(
            _markdown_table(table, "Table 1. Summary by country.", lang), encoding="utf-8"
        )

    # --- Table 2: climate indicators by country --------------------------
    indicators = _read_table("t02_climate_by_country.csv")
    if not indicators.empty:
        # The CSV has one row per country-indicator. Pivot so countries are
        # columns and indicators are rows - much easier to read.
        wide = indicators.pivot(index="indicator", columns="iso3", values="mean")
        wide = wide.reset_index().rename(columns={"indicator": "Indicator"})
        order = ["hd35", "tr25", "cdd", "wbal", "rx1d", "r50"]
        wide["_order"] = wide["Indicator"].map({name: i for i, name in enumerate(order)})
        wide = wide.sort_values("_order").drop(columns="_order")
        (out_dir / "t02.md").write_text(
            _markdown_table(wide, "Table 2. Mean climate indicators by country, 2004-2023.", lang),
            encoding="utf-8",
        )

    # --- Table 3: highest-risk regions -----------------------------------
    extremes = _read_table("t03_top_bottom_regions.csv")
    if not extremes.empty:
        top = extremes[extremes["group"] == "highest_risk"].head(10)
        table = top[["region_name", "iso3", "population", "hazard_equal",
                     "exposure_score", "vulnerability", "risk_equal"]].copy()
        table["population"] = (table["population"] / 1e6).round(1)
        table = table.rename(columns={
            "region_name": "Region", "iso3": "Country",
            "population": "Population (m)", "hazard_equal": "Hazard",
            "exposure_score": "Exposure", "vulnerability": "Vulnerability",
            "risk_equal": "Risk",
        })
        (out_dir / "t03.md").write_text(
            _markdown_table(table, "Table 3. The ten highest-risk regions.", lang),
            encoding="utf-8",
        )

    # --- Table 4: hypothesis tests ---------------------------------------
    tests = _read_table("t05_hypothesis_tests.csv")
    if not tests.empty:
        h1 = tests.iloc[0]
        h2 = tests.iloc[1]
        rows = [
            ("H1 Concentration ratio", _fmt(h1["concentration_ratio"], 2, lang),
             _interval(h1["ci_low"], h1["ci_high"], lang, 2), "-"),
            ("H1 Share of person-days, top 10%", _pct(h1["top_region_share_person_days"], 1, lang),
             "-", "-"),
            ("H1 Share of population, top 10%", _pct(h1["top_region_share_population"], 1, lang),
             "-", "-"),
            ("H2 Median SHDI, high hazard", _fmt(h2["median_shdi_high_hazard"], 3, lang), "-", "-"),
            ("H2 Median SHDI, low hazard", _fmt(h2["median_shdi_low_hazard"], 3, lang), "-", "-"),
            ("H2 Mann-Whitney p", "-", "-", _sci(h2["p_value"], lang)),
            ("H2 Cliff's delta", _fmt(h2["cliffs_delta"], 2, lang), "-", "-"),
            ("H2 Spearman rho", _fmt(h2["spearman_rho"], 2, lang), "-", "-"),
            ("H2 Spearman p", "-", "-", _sci(h2["spearman_p"], lang)),
        ]
        table = pd.DataFrame(rows, columns=["Test", "Estimate", "95% CI", "p-value"])
        (out_dir / "t05.md").write_text(
            _markdown_table(table, "Table 4. Hypothesis tests H1 and H2.", lang),
            encoding="utf-8",
        )

    # --- Table 5: rank stability -----------------------------------------
    stability = _read_table("t06_rank_stability.csv")
    if not stability.empty:
        table = stability.rename(columns={
            "version_a": "Version A", "version_b": "Version B",
            "n_regions": "Regions", "spearman_rho": "Spearman rho",
            "p_value": "p-value",
        })
        (out_dir / "t06.md").write_text(
            _markdown_table(table, "Table 5. Agreement between index versions.", lang),
            encoding="utf-8",
        )

    # --- Table 6: regression coefficients --------------------------------
    coefficients = _read_table("t07_regression_coefficients.csv")
    if not coefficients.empty:
        wanted = ["hazard_equal_z", "hazard_heat_z", "hazard_dry_z", "hazard_wet_z",
                  "abs_lat_z", "log_density_z", "remote"]
        table = coefficients[coefficients["term"].isin(wanted)].copy()
        table["estimate"] = table.apply(
            lambda row: f"{_fmt(row['beta'], 3, lang)} "
                        f"({_interval(row['ci_low'], row['ci_high'], lang, 3)})",
            axis=1,
        )
        table["significance"] = table["p_value"].map(
            lambda p: "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        )
        table = table[["model", "term", "estimate", "significance", "n_obs", "r_squared"]]
        table = table.rename(columns={
            "model": "Model", "term": "Variable", "estimate": "Beta (95% CI)",
            "significance": "Sig.", "n_obs": "N", "r_squared": "R squared",
        })
        (out_dir / "t07.md").write_text(
            _markdown_table(table, "Table 6. Regression coefficients (standardised).", lang),
            encoding="utf-8",
        )

    # --- Table 7: country slopes -----------------------------------------
    slopes = _read_table("t08_country_slopes.csv")
    if not slopes.empty:
        table = slopes.copy()
        table["estimate"] = table.apply(
            lambda row: f"{_fmt(row['slope'], 3, lang)} "
                        f"({_interval(row['ci_low'], row['ci_high'], lang, 3)})",
            axis=1,
        )
        table = table[["iso3", "n_regions", "estimate", "p_value", "r_squared"]]
        table = table.rename(columns={
            "iso3": "Country", "n_regions": "Regions", "estimate": "Slope (95% CI)",
            "p_value": "p-value", "r_squared": "R squared",
        })
        (out_dir / "t08.md").write_text(
            _markdown_table(table, "Table 7. Within-country slope of SHDI on hazard.", lang),
            encoding="utf-8",
        )

    # --- Table 8: Moran's I ----------------------------------------------
    moran = _read_table("t09_morans_i.csv")
    if not moran.empty:
        within = moran[moran["scope"] != "all countries"].copy()
        table = within[["scope", "variable", "n_regions", "morans_i", "p_sim"]]
        table = table.rename(columns={
            "scope": "Scope", "variable": "Variable", "n_regions": "Regions",
            "morans_i": "Moran's I", "p_sim": "p (simulated)",
        })
        # Pivot to one row per variable and one column per country.
        wide = table.pivot_table(index="Variable", columns="Scope",
                                 values="Moran's I", aggfunc="first").reset_index()
        (out_dir / "t09.md").write_text(
            _markdown_table(wide, "Table 8. Moran's I by country (Queen contiguity).", lang),
            encoding="utf-8",
        )

    # --- Validation ------------------------------------------------------
    cfg = load_config()
    validation = Path(cfg["paths"]["outputs"]) / "report" / "validation.md"
    if validation.exists():
        text = validation.read_text(encoding="utf-8")
        if lang == "fr":
            text = _french_validation(text)
        (out_dir / "validation.md").write_text(text, encoding="utf-8")
    else:
        (out_dir / "validation.md").write_text(
            "Data checks have not been run. Run `cro validate` first.\n", encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# 2. Render with Quarto (preferred)
# ---------------------------------------------------------------------------

def _quarto_available() -> str | None:
    """Return the path to the Quarto executable, or None."""
    found = shutil.which("quarto")
    if found:
        return found

    # winget installs Quarto outside PATH in the current shell, so we also
    # look in the usual Windows install location.
    candidates = [
        # System-wide install (how the Quarto installer normally places it).
        Path("C:/Program Files/Quarto/bin/quarto.exe"),
        # Per-user install (used by the zip download fallback).
        Path.home() / "AppData" / "Local" / "Programs" / "Quarto" / "bin" / "quarto.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def render_with_quarto(quarto: str) -> bool:
    """Render HTML (and PDF when LaTeX is available)."""
    log("report: rendering with Quarto")

    html = subprocess.run(
        [quarto, "render", QMD_PATH.name, "--to", "html"],
        cwd=REPORT_DIR, capture_output=True, text=True,
    )
    if html.returncode != 0:
        log("report: Quarto HTML build failed")
        print(html.stderr[-2000:])
        return False

    # Quarto writes report.html next to the .qmd. Copy it to outputs/report
    # so every deliverable sits in one place.
    cfg = load_config()
    target_dir = Path(cfg["paths"]["outputs"]) / "report"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPORT_DIR / "report.html", target_dir / "report.html")
    log(f"report: wrote {target_dir / 'report.html'}")

    # PDF needs a LaTeX installation. It is optional, so a failure here is a
    # warning rather than an error.
    pdf = subprocess.run(
        [quarto, "render", QMD_PATH.name, "--to", "pdf"],
        cwd=REPORT_DIR, capture_output=True, text=True,
    )
    if pdf.returncode == 0:
        shutil.copy(REPORT_DIR / "report.pdf", target_dir / "report.pdf")
        log(f"report: wrote {target_dir / 'report.pdf'}")
    else:
        log("report: PDF not built (LaTeX/TinyTeX missing). "
            "Install it with: quarto install tinytex")

    return True


def render_french(quarto: str) -> bool:
    """Render the French HTML and PDF next to the English ones."""
    if not QMD_FR_PATH.exists():
        log("report: report.fr.qmd not found, skipping the French version")
        return False

    log("report: rendering the French version with Quarto")

    html = subprocess.run(
        [quarto, "render", QMD_FR_PATH.name, "--to", "html"],
        cwd=REPORT_DIR, capture_output=True, text=True,
    )
    if html.returncode != 0:
        log("report: Quarto French HTML build failed")
        print(html.stderr[-2000:])
        return False

    cfg = load_config()
    target_dir = Path(cfg["paths"]["outputs"]) / "report"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPORT_DIR / "report.fr.html", target_dir / "report.fr.html")
    log(f"report: wrote {target_dir / 'report.fr.html'}")

    pdf = subprocess.run(
        [quarto, "render", QMD_FR_PATH.name, "--to", "pdf"],
        cwd=REPORT_DIR, capture_output=True, text=True,
    )
    if pdf.returncode == 0:
        shutil.copy(REPORT_DIR / "report.fr.pdf", target_dir / "report.fr.pdf")
        log(f"report: wrote {target_dir / 'report.fr.pdf'}")
    else:
        log("report: French PDF not built (LaTeX/TinyTeX missing).")

    return True


# ---------------------------------------------------------------------------
# 3. Fallback: build HTML with the markdown package
# ---------------------------------------------------------------------------

def _expand_includes(text: str) -> str:
    """Replace Quarto's `{{< include file >}}` with the file contents."""
    import re

    def replace(match):
        path = GENERATED_DIR / match.group(1).strip()
        return path.read_text(encoding="utf-8") if path.exists() else ""

    return re.sub(r"\{\{<\s*include\s+([^>]+?)\s*>\}\}", replace, text)


def _convert_callouts(text: str) -> str:
    """Turn Quarto callout blocks into blockquotes for the fallback build.

    Quarto's `::: {.callout-note}` fences are not standard Markdown. Without
    this step the fallback page would print the fences as literal text.
    """
    lines = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(":::") and "callout" in stripped:
            inside = True
            lines.append("")
            continue
        if inside and stripped == ":::":
            inside = False
            lines.append("")
            continue
        if inside and stripped:
            lines.append("> " + line)
        else:
            lines.append(line)
    return "\n".join(lines)


def render_fallback() -> bool:
    """Build a stand-alone HTML file without Quarto.

    This is intentionally simple: headings, paragraphs, lists, tables and
    images are enough for the report. The result is not as polished as the
    Quarto version, but it means the project never depends on a tool that
    might not be installed.
    """
    try:
        import markdown
    except ImportError:
        log("report: neither Quarto nor the `markdown` package is available. "
            "Install one with: pip install markdown")
        return False

    cfg = load_config()
    target_dir = Path(cfg["paths"]["outputs"]) / "report"
    target_dir.mkdir(parents=True, exist_ok=True)

    raw = QMD_PATH.read_text(encoding="utf-8")

    # Drop the YAML header (everything up to the second '---').
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        body = parts[2] if len(parts) > 2 else raw
    else:
        body = raw

    body = _expand_includes(body)
    body = _convert_callouts(body)

    # The page will live in outputs/report, so figures are one level up
    # from outputs/. Rewrite the paths written for the Quarto build.
    body = body.replace("](../outputs/", "](../")

    html_body = markdown.markdown(
        body,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
    )

    css = """
    body { max-width: 900px; margin: 40px auto; padding: 0 20px;
           font-family: "Segoe UI", system-ui, sans-serif; color: #1b2a3a;
           line-height: 1.6; }
    h1, h2, h3 { line-height: 1.25; }
    h2 { border-bottom: 1px solid #e2e8ef; padding-bottom: 6px; margin-top: 42px; }
    img { max-width: 100%; border: 1px solid #e2e8ef; }
    table { border-collapse: collapse; font-size: 0.86rem; margin: 14px 0; }
    th, td { border-bottom: 1px solid #e2e8ef; padding: 6px 10px; text-align: left; }
    th { border-bottom: 2px solid #2f6f8f; }
    code { background: #f4f6f8; padding: 1px 4px; border-radius: 3px; }
    blockquote, .callout-note, .callout-warn {
      border-left: 4px solid #2f6f8f; background: #f2f7fa;
      margin: 16px 0; padding: 10px 16px; }
    .callout-warn { border-left-color: #c8553d; background: #fdf4f2; }
    """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Climate Risk and Human Development</title>
<style>{css}</style>
</head>
<body>
{html_body}
</body>
</html>
"""
    out_path = target_dir / "report.html"
    out_path.write_text(html, encoding="utf-8")
    log(f"report: wrote {out_path} (fallback renderer, no Quarto)")
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    cfg = load_config()
    outputs = Path(cfg["paths"]["outputs"])

    # A quick guard: figures must exist before we build a report that links
    # to them, otherwise the reader gets a page full of broken images.
    if not (outputs / "figures").exists() or not list((outputs / "figures").glob("*.png")):
        log("report: no figures found. Run `cro export` first.")
        return

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_FR.mkdir(parents=True, exist_ok=True)
    write_summary_snippet("en")
    write_summary_snippet("fr")
    write_table_snippets("en")
    write_table_snippets("fr")
    log(f"report: wrote English snippets to {GENERATED_DIR}")
    log(f"report: wrote French snippets to {GENERATED_FR}")

    quarto = _quarto_available()
    if quarto:
        rendered = render_with_quarto(quarto)
        # The French report is optional for the build to succeed: a missing
        # translation should never stop the English deliverables.
        render_french(quarto)
        if rendered:
            return

    if not render_fallback():
        sys.exit(1)


if __name__ == "__main__":
    run()
