# Climate Risk & Human Development Observatory

[Français](README.md) | **English**

Author: **Chengho Fongang Marie Louise**

**Are the regions with the most extreme climate also the regions with the lowest human development?**

This project is a data pipeline in Python. It downloads open data on climate, population and
human development, builds a climate risk index for each region, tests three hypotheses, and
shows the results in maps, a written report (English and French) and a web dashboard.

The pilot covers **105 admin-1 regions** (states, provinces, regions) in **France, India and the
United States**, about 1.8 billion people. The same code can run on other countries by changing
the configuration file.

---

## Main results

| Hypothesis | Result |
|---|---|
| **H1.** Regions with more climate hazard have a lower SHDI | Yes on all regions: Spearman rho = **-0.59**, median SHDI **0.786** vs **0.936**. But most of it is the gap between India and the two other countries. Inside countries: rho = -0.48 in India, -0.48 in the USA, +0.18 in France (not significant). |
| **H2.** This is still true inside each country | Yes, but smaller: the hazard coefficient goes from **-0.39** to **-0.10** (95% CI -0.14 to -0.06) when we add a country effect. Clear in India and the USA, not in France. |
| **H3.** The ranking is stable when we change the index formula | Yes: the three versions have rank correlations of at least **0.86**, and at least **9 of the top 10** regions are the same. |

All ten highest-risk regions are in India (Bihar, Uttar Pradesh, Madhya Pradesh...). Inside
their own country, the highest-risk regions are Texas, Alabama and Louisiana (USA) and
Auvergne-Rhône-Alpes, Occitanie and Nouvelle-Aquitaine (France).

These results are **associations, not causes**.

---

## Technologies

| Area | Tools |
|---|---|
| Language | Python 3.10+ |
| Data processing | Pandas, NumPy, PyArrow (Parquet) |
| Geospatial | GeoPandas, Shapely, PyProj, Rasterio |
| Statistics | SciPy (Spearman correlation), Statsmodels (OLS regression, HC3 robust errors) |
| Database | PostgreSQL + PostGIS (Docker), SQLAlchemy, GeoAlchemy2 |
| Maps and charts | Plotly, Matplotlib, Kaleido |
| Dashboard | Plotly Dash, Dash Bootstrap Components |
| Report | Quarto (HTML + PDF, English and French), Jupyter notebook |
| Testing | pytest |
| Deployment | Docker, Docker Compose, Render |

---

## How the index is built

Each indicator is turned into a **percentile rank** between 0 and 1, so we can mix days,
millimetres and index points.

```
Hazard        = mean(heat, dry, wet)     heat = mean rank of HD35 and TR25
                                         dry  = mean rank of CDD and -WBAL
                                         wet  = mean rank of Rx1day and R50

Exposure      = rank(population)

Vulnerability = 1 - rank(SHDI)

Risk          = Hazard x Exposure x Vulnerability
```

- We use a **product** because, following the IPCC, a region needs all three parts to be at risk:
  a hot desert with nobody living there is not a disaster.
- **Exposure uses population only.** Heat is already in the hazard score; if we also used
  "population x heat days" here, heat would be counted twice.
- Two other versions are used to check the ranking (H3): `additive` (mean of the three scores)
  and `per_person` (hazard x vulnerability, without population, to check that the ranking is not
  only a size effect).
- `rank_in_country` gives the risk rank of each region inside its own country.

## Statistical tests

| Hypothesis | Method | Code |
|---|---|---|
| H1 | Spearman correlation hazard vs SHDI, on all regions and in each country; median SHDI of the more and less hazardous halves | `src/cro/analysis/tests.py` |
| H2 | Linear regression (OLS, HC3 robust errors): M1 `shdi ~ hazard`, M2 `shdi ~ hazard + country dummies`; the same line fitted in each country | `src/cro/analysis/regression.py` |
| H3 | Spearman correlation between the rankings of the three versions + number of shared top-10 regions | `src/cro/analysis/tests.py` |

---

## Walkthrough notebook

`notebooks/exploration.ipynb` tells the story of the project step by step: the data, how the
index is built, the maps and the three hypotheses. It imports the same functions as the
pipeline (`src/cro/`) and only needs `data/processed/dashboard_regions.parquet`, which is in
the repository, so it runs right after `git clone`. GitHub shows it with all its tables and
charts. A French version is in `notebooks/exploration.fr.ipynb`.

---

## Quick start

```bash
# 1. Environment
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e .

# 2. Check that the data sources are reachable
cro probe

# 3. Run the pipeline (downloads ~500 MB once, then uses a cache)
cro all

# 4. Checks, outputs, report
cro validate
cro export
cro report

# 5. Dashboard
cro app            # http://127.0.0.1:8050
```

Each step can also be run alone:

| Command | What it does |
|---|---|
| `cro boundaries` | Download admin-1 polygons from geoBoundaries |
| `cro climate-points` | Choose climate sample points inside each region |
| `cro population` | Population per region and per sample point (GHS-POP) |
| `cro climate` | Download daily NASA POWER data and compute the yearly indicators |
| `cro development` | SHDI from Global Data Lab + WDI from the World Bank |
| `cro build` | Build hazard, exposure, vulnerability and the three risk versions |
| `cro analyze` | Descriptive tables, H1 and H3 tests, H2 regressions |
| `cro export` | 11 static maps, 6 figures, 4 interactive maps |
| `cro report` | Build the report tables and render the report (EN + FR) with Quarto |
| `cro validate` | 8 data checks (exit code 1 if one fails) |
| `cro load` | Load the tables into PostGIS |
| `cro app` | Start the Plotly Dash dashboard |
| `cro all` | Run ingest -> build -> analyze -> export in order |

---

## Dashboard

`cro app` opens one scrolling page at <http://127.0.0.1:8050>:

- **the map** - one panel per country. Choose *all* to compare the three countries on one colour
  scale, or one country to see its internal differences.
- **the ranking** - the ten regions with the highest value of the chosen measure.
- **the relationship** - hazard against SHDI, with one trend line per country and the H1/H2/H3
  results next to it (read from the result tables, never typed by hand).
- **one place** - the numbers of one region and its position compared with the others.
- **methods & data** - how the index is built and its limits.

Other pages on the same server:

- `/summary` - a two-minute summary of the report (`/summary?lang=fr` in French)
- `/report` and `/report.pdf` - the full report (`/report/fr` and `/report/fr.pdf` in French)
- `/maps/map_web_risk.html` (and `hazard`, `exposure`, `shdi`) - interactive maps

Every page has an **EN / FR** switch. The dashboard reads PostGIS when it is running and the
Parquet files otherwise, so it works without Docker.

## Deployment

The app is live on Render's free plan: **<https://climate-risk-observatory.onrender.com>**.
The free instance sleeps after 15 minutes without visitors, so the first request can take about
a minute.

`render.yaml` is the Render blueprint and `requirements-deploy.txt` lists only the packages the
app needs. See **[docs/deploy.md](docs/deploy.md)** for the steps.

---

## Repository layout

```
config/config.yaml              all settings (countries, thresholds, years)
src/cro/ingest/                 download boundaries, climate, population, development
src/cro/features/build.py       hazard, exposure, vulnerability, risk versions
src/cro/analysis/               descriptive tables, H1/H3 tests, H2 regression
src/cro/viz/                    shared theme, static maps, charts, interactive maps
src/cro/app/                    Dash dashboard + summary and report pages
src/cro/app/i18n.py             all English/French texts of the dashboard
src/cro/db/                     PostGIS schema and loader
src/cro/report/                 report tables + Quarto rendering
report/                         report.qmd / report.fr.qmd
notebooks/exploration.ipynb     step-by-step walkthrough of the results (uses src/cro)
notebooks/exploration.fr.ipynb  the same walkthrough in French
tests/                          unit tests, data checks, dashboard tests
data/processed/                 intermediate tables (Parquet)
outputs/maps|figures|tables/    results
outputs/report/                 report(.fr).html/.pdf, validation.md, key_results.md
```

`data/processed/region_master.parquet` is the one table that every output reads, so the maps,
the tables and the dashboard always agree.

### Output tables

| File | Content |
|---|---|
| `t01_summary_by_country.csv` | means by country |
| `t02_climate_by_country.csv` | climate indicators by country |
| `t03_top_bottom_regions.csv` | highest and lowest risk regions |
| `t05_hypothesis_tests.csv` | H1: Spearman correlation, all regions and by country |
| `t06_rank_stability.csv` | H3: agreement between the three index versions |
| `t07_regression_coefficients.csv` | H2: models M1 and M2 |
| `t08_country_slopes.csv` | H2: slope in each country |

---

## Data sources and licences

| Layer | Source | Resolution | Year | Licence |
|---|---|---|---|---|
| Boundaries | [geoBoundaries](https://www.geoboundaries.org/) (gbOpen) | admin-1 polygons | 2024 release | CC-BY 4.0 |
| Climate | [NASA POWER](https://power.larc.nasa.gov/) (MERRA-2) | daily point series | 1991-2023 | Open, no key |
| Population | [GHS-POP R2023A](https://ghsl.jrc.ec.europa.eu/) | ~1 km | 2020 | CC-BY 4.0 |
| Development | [Global Data Lab SHDI](https://globaldatalab.org/shdi/) | admin-1 | latest available | Free for research |
| National context | [World Bank WDI](https://databank.worldbank.org/source/world-development-indicators) | country | 2010-2023 | CC-BY 4.0 |

NASA POWER does not give evapotranspiration, so we estimate it with the Hargreaves formula
(Hargreaves & Samani, 1985) from daily minimum/maximum temperature and latitude.

---

## Quality and tests

- `cro validate` runs 8 data checks: unique regions, valid geometry, population totals, physical
  ranges, scores between 0 and 1, SHDI coverage, master table and output tables.
- `pytest -q` runs the tests:
  - `tests/test_indicators.py` - the index maths and the statistical functions on small examples;
  - `tests/test_data_contract.py` - checks on the real files (skipped before the pipeline runs);
  - `tests/test_presentation.py` - maps, dashboard callbacks and pages.
- The report and the dashboard read their numbers from the same CSV tables.

## PostGIS (optional)

```bash
docker compose up -d
cro load
```

This creates `dim_region`, `dim_country`, `fact_climate`, `fact_population`, `fact_exposure`,
`fact_development`, `fact_risk` (one row per region and index version) and the view
`vw_region_profile` on port **5433**.

---

## Limitations

1. **Association, not causation.** History, geography and the economy can explain both climate
   and development.
2. **Neighbouring regions are similar.** The tests treat regions as independent, so the p-values
   are probably too small. A spatial regression model would be the next step.
3. **Small sample.** 99 regions with SHDI; France has only 13, so its results are uncertain.
4. **One development indicator.** SHDI does not show inequality inside a region.
5. **Fixed thresholds.** 35 C and 50 mm are choices; France has almost no days above 35 C.
6. **Static population.** Population is for 2020; the climate mean is for 2004-2023.
7. **Coarse sampling.** At most 8 climate points per region.
8. **Pilot countries.** France, India and the USA were chosen because they are different, not
   because they represent the world.

## Next steps

- Add more countries: set `project.pilot_iso3` in `config/config.yaml` (for example `["ALL"]`).
- Use a spatial regression model.
- Add a household income indicator to see inequality inside regions.
- Test other heat thresholds (30 C, 40 C).

## Key references

The full list is in the report. The main method choices follow:

- **Risk = hazard x exposure x vulnerability:** Cardona et al. (2012), IPCC SREX chapter 2; IPCC (2014), AR5 WGII.
- **Multiplicative risk index:** Marin-Ferrer, Vernaccini & Poljansek (2017), INFORM methodology (European Commission JRC).
- **Rank normalisation and robustness checks:** Nardo et al. (2008), OECD/JRC *Handbook on Constructing Composite Indicators*; Saisana, Saltelli & Tarantola (2005), *JRSS A* 168(2).
- **Climate extreme indicators:** Zhang et al. (2011), *WIREs Climate Change* 2(6).
- **Climate and income inside countries:** Dell, Jones & Olken (2009), *American Economic Review* 99(2); Nordhaus (2006), *PNAS* 103(10).
- **Subnational HDI:** Smits & Permanyer (2019), *Scientific Data* 6.
