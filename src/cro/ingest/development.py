"""Development data from two places.

1. Global Data Lab (GDL) publishes the Subnational Human Development Index
   (SHDI) for regions inside many countries. This is our main development
   outcome because it varies *within* countries, which the analysis needs.

2. The World Bank World Development Indicators (WDI) give national values
   for poverty, services and income. These do not vary inside a country,
   but they are useful context and are used for country-level checks.

The hard part is matching region names. GDL spellings differ from
geoBoundaries (for example "Orissa" vs "Odisha"), and France is still split
into its pre-2016 regions. We handle this with a small manual crosswalk
plus fuzzy matching, and we save the match table so it can be checked.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

from cro.config import load_config
from cro.utils import log, save_table

# ---------------------------------------------------------------------------
# World Bank indicators
# ---------------------------------------------------------------------------

# Left side = our indicator name, right side = World Bank indicator code.
WDI_INDICATORS = {
    "poverty_headcount": "SI.POV.DDAY",
    "life_expectancy": "SP.DYN.LE00.IN",
    "electricity_access": "EG.ELC.ACCS.ZS",
    "sanitation_access": "SH.STA.SMSS.ZS",
    "stunting": "SH.STA.STNT.ZS",
    "urban_share": "SP.URB.TOTL.IN.ZS",
    "agri_employment": "SL.AGR.EMPL.ZS",
    "gdp_pc": "NY.GDP.PCAP.PP.KD",
    "gini": "SI.POV.GINI",
    "school_enrolment": "SE.SEC.ENRR",
}

WDI_URL = "https://api.worldbank.org/v2/country/{iso3}/indicator/{code}"


def fetch_wdi(iso3: str, years: str = "2010:2023") -> pd.DataFrame:
    """Download one indicator for one country and keep the latest value."""
    rows = []
    for name, code in WDI_INDICATORS.items():
        params = {"format": "json", "per_page": 1000, "date": years}
        try:
            response = requests.get(WDI_URL.format(iso3=iso3, code=code),
                                    params=params, timeout=60)
            payload = response.json()
        except Exception as error:
            log(f"wdi: {iso3} {code} failed ({error})")
            continue

        # The API returns [metadata, data]. data can be None for a bad code.
        data = payload[1] if isinstance(payload, list) and len(payload) > 1 else None
        if not data:
            continue

        for item in data:
            if item.get("value") is not None:
                rows.append({
                    "iso3": iso3,
                    "indicator": name,
                    "year": int(item["date"]),
                    "value": float(item["value"]),
                    "source": "World Bank WDI",
                })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    # Keep the most recent observation for each indicator.
    df = df.sort_values("year").groupby(["iso3", "indicator"], as_index=False).last()
    return df


# ---------------------------------------------------------------------------
# Global Data Lab subnational HDI
# ---------------------------------------------------------------------------

GDL_URL = "https://globaldatalab.org/shdi/table/shdi/{iso3}/"


def fetch_gdl_shdi(iso3: str) -> pd.DataFrame:
    """Scrape the GDL SHDI table for one country.

    The table has regions as rows and years as columns. We return a long
    table and keep the most recent year for each region.
    """
    try:
        response = requests.get(GDL_URL.format(iso3=iso3), timeout=60,
                                headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    except Exception as error:
        log(f"gdl: {iso3} failed ({error})")
        return pd.DataFrame()

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table")
    if table is None:
        return pd.DataFrame()

    # The first row of the header contains the years.
    header_cells = table.find("thead").find_all("th")
    years = []
    for cell in header_cells:
        text = cell.get_text(strip=True)
        if re.fullmatch(r"(19|20)\d{2}", text):
            years.append(int(text))

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        name = cells[0].get_text(" ", strip=True)
        values = [cell.get_text(strip=True) for cell in cells[1:]]

        # Skip the national total line and empty names.
        if not name or name.lower() in {"total", "region"}:
            continue

        series = {}
        for year, value in zip(years, values):
            try:
                series[year] = float(value)
            except (TypeError, ValueError):
                continue

        if not series:
            continue

        latest_year = max(series)
        rows.append({
            "iso3": iso3,
            "gdl_name": name,
            "year": latest_year,
            "value": series[latest_year],
            "source": "Global Data Lab SHDI",
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

# A few known differences that fuzzy matching alone would get wrong.
# The left side is the geoBoundaries name, the right side is the GDL name.
MANUAL_MATCHES = {
    "IND": {
        "Delhi": "New Delhi",
        "Odisha": "Orissa",
        "Uttarakhand": "Uttaranchal",
    },
    "USA": {
        "District of Columbia": "District of Columbia",
    },
}

# Some GDL units no longer exist in the boundary file, or the boundary file
# merges two old units. We rebuild the combined value as a simple mean.
INDIA_AGGREGATION = {
    "Dadra and Nagar Haveli and Daman and Diu": [
        "Dadra and Nagar Haveli", "Daman and Diu",
    ],
}

# France: GDL still uses the 22 old regions, geoBoundaries uses the 13 new
# ones. We aggregate the old regions into the new ones with a simple mean.
FRANCE_AGGREGATION = {
    "Grand Est": ["Alsace", "Champagne-Ardenne", "Lorraine"],
    "Nouvelle-Aquitaine": ["Aquitaine", "Limousin", "Poitou-Charentes"],
    "Auvergne-Rhone-Alpes": ["Auvergne", "Rhone-Alpes"],
    "Bourgogne-Franche-Comte": ["Bourgogne", "Franche-Comte"],
    "Occitanie": ["Languedoc-Roussillon", "Midi-Pyrenees"],
    "Hauts-de-France": ["Nord-Pas-de-Calais", "Picardie"],
    "Normandie": ["Basse-Normandie", "Haute-Normandie"],
    "Bretagne": ["Bretagne"],
    "Centre-Val de Loire": ["Centre"],
    "Corse": ["Corse"],
    "Ile-de-France": ["Ile-de-France"],
    "Pays de la Loire": ["Pays de la Loire"],
    "Provence-Alpes-Cote d'Azur": ["Provence-Alpes-Cote d'Azur"],
}


def normalise_name(name: str) -> str:
    """Lowercase, remove accents and punctuation so names can be compared."""
    text = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"\b(state|province|region|department|of|the)\b", " ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def build_crosswalk(regions: pd.DataFrame, gdl: pd.DataFrame, iso3: str) -> pd.DataFrame:
    """Match every geoBoundaries region to a GDL region name.

    Match quality is recorded so the report can show how many regions were
    matched and how reliable the match is.
    """
    country_regions = regions[regions["iso3"] == iso3].copy()
    if gdl.empty:
        return pd.DataFrame()

    gdl_names = gdl["gdl_name"].tolist()
    gdl_lookup = {normalise_name(n): n for n in gdl_names}
    overrides = {normalise_name(k): v for k, v in MANUAL_MATCHES.get(iso3, {}).items()}

    rows = []
    for region in country_regions.itertuples():
        target = normalise_name(region.region_name)
        matched = None
        score = 0.0
        method = "none"

        # 1. Manual override.
        if target in overrides:
            matched = overrides[target]
            score = 1.0
            method = "manual"

        # 2. Exact match after normalisation.
        elif target in gdl_lookup:
            matched = gdl_lookup[target]
            score = 1.0
            method = "exact"

        # 3. Fuzzy match.
        else:
            best_name, best_score = None, 0.0
            for candidate in gdl_names:
                candidate_norm = normalise_name(candidate)
                candidate_score = SequenceMatcher(None, target, candidate_norm).ratio()
                if candidate_score > best_score:
                    best_name, best_score = candidate, candidate_score
            if best_score >= 0.85:
                matched = best_name
                score = best_score
                method = "fuzzy"

        rows.append({
            "region_id": region.region_id,
            "iso3": iso3,
            "region_name": region.region_name,
            "gdl_name": matched,
            "match_score": round(float(score), 3),
            "match_method": method,
        })

    return pd.DataFrame(rows)


def aggregate_france(gdl: pd.DataFrame) -> pd.DataFrame:
    """Rebuild SHDI for the 13 new French regions from the old regions."""
    return aggregate_units(gdl, FRANCE_AGGREGATION, "FRA")


def aggregate_units(gdl: pd.DataFrame, mapping: dict, iso3: str) -> pd.DataFrame:
    """Combine several GDL units into one region using their mean value."""
    # Match names without accents so "Rhone-Alpes" and "Rhône-Alpes" agree.
    values = {normalise_name(name): value for name, value in zip(gdl["gdl_name"], gdl["value"])}
    latest_year = int(gdl["year"].max()) if not gdl.empty else None

    rows = []
    for new_name, old_names in mapping.items():
        available = [values[normalise_name(name)] for name in old_names
                     if normalise_name(name) in values]
        if available:
            rows.append({
                "iso3": iso3,
                "gdl_name": new_name,
                "year": latest_year,
                "value": float(sum(available) / len(available)),
                "source": "Global Data Lab SHDI (aggregated)",
                "note": "mean of older units",
            })
    return pd.DataFrame(rows)


def replace_old_units(gdl: pd.DataFrame, mapping: dict, iso3: str) -> pd.DataFrame:
    """Swap the old units for the new combined units."""
    combined = aggregate_units(gdl, mapping, iso3)
    if combined.empty:
        return gdl

    old_names = {normalise_name(name) for names in mapping.values() for name in names}
    keep = gdl[~gdl["gdl_name"].map(normalise_name).isin(old_names)]
    return pd.concat([keep, combined], ignore_index=True)


# ---------------------------------------------------------------------------
# Combine
# ---------------------------------------------------------------------------

def run() -> pd.DataFrame:
    cfg = load_config()
    processed = Path(cfg["paths"]["processed"])

    regions = pd.read_parquet(processed / "regions.parquet")
    iso3_list = sorted(regions["iso3"].unique())

    shdi_frames = []
    for iso3 in iso3_list:
        log(f"development: GDL SHDI {iso3}")
        gdl = fetch_gdl_shdi(iso3)
        if gdl.empty:
            continue
        if iso3 == "FRA":
            # GDL still uses the 22 old French regions; rebuild the 13 new ones.
            gdl = replace_old_units(gdl, FRANCE_AGGREGATION, "FRA")
        elif iso3 == "IND":
            # Two old districts were merged into one union territory.
            gdl = replace_old_units(gdl, INDIA_AGGREGATION, "IND")
        shdi_frames.append(gdl)

    all_shdi = pd.concat(shdi_frames, ignore_index=True) if shdi_frames else pd.DataFrame()
    if not all_shdi.empty:
        all_shdi = all_shdi.drop_duplicates(["iso3", "gdl_name"])
    save_table(all_shdi, processed / "gdl_shdi_raw.parquet")

    # Match GDL names to our region IDs.
    crosswalks = []
    for iso3 in iso3_list:
        gdl_country = all_shdi[all_shdi["iso3"] == iso3] if not all_shdi.empty else pd.DataFrame()
        crosswalk = build_crosswalk(regions, gdl_country, iso3)
        if not crosswalk.empty:
            crosswalks.append(crosswalk)

    crosswalk = pd.concat(crosswalks, ignore_index=True) if crosswalks else pd.DataFrame()
    save_table(crosswalk, processed / "region_name_crosswalk.parquet")

    # Join SHDI values onto the crosswalk to get region-level development.
    if not all_shdi.empty and not crosswalk.empty:
        shdi = crosswalk.merge(
            all_shdi[["iso3", "gdl_name", "value", "year", "source"]],
            on=["iso3", "gdl_name"], how="left"
        )
        shdi = shdi.rename(columns={"value": "shdi", "year": "shdi_year"})
    else:
        shdi = crosswalk.assign(shdi=None, shdi_year=None, source=None)

    # National WDI values. These are attached to every region in the country
    # with level="national" so they are not mistaken for subnational data.
    wdi_frames = []
    for iso3 in iso3_list:
        log(f"development: World Bank WDI {iso3}")
        wdi = fetch_wdi(iso3)
        if not wdi.empty:
            wdi_frames.append(wdi)

    wdi = pd.concat(wdi_frames, ignore_index=True) if wdi_frames else pd.DataFrame()
    save_table(wdi, processed / "wdi_national.parquet")

    # Build the final long table used by the feature step.
    rows = []
    for record in shdi.itertuples():
        if pd.notna(record.shdi):
            rows.append({
                "region_id": record.region_id,
                "iso3": record.iso3,
                "indicator": "shdi",
                "value": float(record.shdi),
                "year": int(record.shdi_year) if pd.notna(record.shdi_year) else None,
                "level": "subnational",
                "source": record.source,
                "match_score": record.match_score,
                "match_method": record.match_method,
            })

    for record in wdi.itertuples():
        country_regions = regions[regions["iso3"] == record.iso3]["region_id"]
        for region_id in country_regions:
            rows.append({
                "region_id": region_id,
                "iso3": record.iso3,
                "indicator": record.indicator,
                "value": float(record.value),
                "year": int(record.year),
                "level": "national",
                "source": "World Bank WDI",
                "match_score": 1.0,
                "match_method": "country",
            })

    development = pd.DataFrame(rows)
    save_table(development, processed / "development_regions.parquet")

    # Print a short coverage summary so the user sees what worked.
    if not crosswalk.empty:
        matched = crosswalk["gdl_name"].notna().sum()
        log(f"development: SHDI matched for {matched}/{len(crosswalk)} regions")
        log(crosswalk["match_method"].value_counts().to_string())

    return development


if __name__ == "__main__":
    run()
