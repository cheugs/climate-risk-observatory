# Climate Risk & Human Development Observatory

**Which admin-1 regions carry the heaviest climate burden, and how does that relate to human development?**

This project builds a reproducible pipeline that puts climate hazard, population exposure and
development on the same map, tests whether the three overlap, and ships the result as a report,
static maps, interactive maps and a dashboard. The pilot covers **105 states, provinces and
regions in France, India and the United States** (1.8 billion people). The same code is written so
that it can be pointed at all ~3,700 admin-1 regions in the world without being rewritten.

---

## Headline results (pilot)

| Question | Result |
|---|---|
| Is climate exposure concentrated? | The top 10% most hazardous regions hold **62%** of person-days of extreme heat while containing 45% of the population: concentration ratio **1.38** (95% CI 1.21-1.75). |
| Do high-hazard regions have lower development? | Median SHDI **0.786** vs **0.936** (Mann-Whitney p = 1.4e-06, Cliff's delta = -0.56). |
| Does that survive comparing within countries? | Yes, but it shrinks: pooled beta = **-0.69**, with country fixed effects beta = **-0.21** (95% CI -0.32 to -0.11, N = 99). |
| Is the ranking sensitive to our choices? | No: four index versions agree at Spearman rho >= **0.96**. |

Everything is an **association, not a causal effect**. The report says so in several places.

---

## Quick start

```bash
# 1. Environment
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e .

# 2. Check that the data sources are still reachable
cro probe

# 3. Run the pipeline (downloads ~500 MB once, then caches)
cro all

# 4. Quality checks, outputs, report
cro validate
cro export
cro report

# 5. Dashboard
cro app            # http://127.0.0.1:8050
```

Run steps individually when iterating:

| Command | What it does |
|---|---|
| `cro boundaries` | Download ADM1 polygons from geoBoundaries |
| `cro climate-points` | Choose climate sample points inside each region |
| `cro population` | Population per region and per sample point (GHS-POP) |
| `cro climate` | Download daily NASA POWER series and build annual indicators |
| `cro development` | SHDI from Global Data Lab + WDI from the World Bank |
| `cro build` | Build hazard, exposure, vulnerability and the four risk versions |
| `cro analyze` | Descriptives, hypothesis tests, regressions, spatial statistics |
| `cro export` | 11 static maps, 6 statistical figures, 4 interactive maps |
| `cro report` | Generate report snippets and render the report |
| `cro validate` | Data-contract checks (exit code 1 on failure) |
| `cro load` | Load everything into PostGIS |
| `cro app` | Start the Plotly Dash dashboard |
| `cro all` | Run ingest -> build -> analyze -> export in order |

---

## Dashboard

`cro app` opens a single scrolling page at <http://127.0.0.1:8050>, styled like an editorial
spread rather than a wall of tabs:

- **02 the map** - one panel per country. Choose *all* to compare the three maps on a shared
  colour scale, or choose one country to enlarge its map and rescale the colours to that country.
- **03 the ranking** - the ten regions with the most of the selected measure. Click a row to load
  it into the profile.
- **04 the relationship** - hazard against SHDI, with the selected region ringed and the headline
  statistics beside it.
- **05 one place** - absolute numbers for one region plus its percentile position on six measures,
  with the country median marked.
- **06 methods & data** - the index definition, sources and the causal caveat.

The controls at the top switch country, map measure and region, and stay pinned while you scroll.
Clicking any map region also loads it into the profile. The dashboard reads PostGIS when it is
running and falls back to the Parquet files, so it works without Docker.

### Reading the written report

The dashboard is the visual entry point, but the argument is written out as well. Two links sit
in the top bar and in the band at the bottom of the page:

- **summary** at <http://127.0.0.1:8050/summary> - a two-minute reading page with the question,
  the index definition, the four findings, the top-ten table, the country table, the caveats and
  links to the full document. Its numbers are rendered from the same `outputs/tables/t01-t09.csv`
  files as the report, so the two cannot drift apart. The hero also links to it, which matters on
  narrow screens where the top bar links are hidden.
- **full report** at <http://127.0.0.1:8050/report> - the self-contained Quarto HTML report.
- **report.pdf** at <http://127.0.0.1:8050/report.pdf> - the print version.

These are plain Flask routes added to the same server, so there is nothing extra to start: run
`cro app` and all three are available. If the report tables are missing, `/summary` still loads
and explains which step to run.

## Deploy it for free

The app is an ordinary Flask server, so it runs on a free host. It reads `PORT` from the
environment and binds to `0.0.0.0`; `requirements-deploy.txt` contains only the runtime packages,
and `render.yaml` is a ready-made Render blueprint. The deployment needs the simplified dashboard
table and the report tables, not the raw downloads.

See **[docs/deploy.md](docs/deploy.md)** for the step-by-step free options: Render (recommended),
a Cloudflare Tunnel from your own computer, and a static-only summary/report. It also explains
what to do if the host has 512 MB of RAM (the app uses about 180 MB) and why Hugging Face Docker
Spaces, PythonAnywhere and Koyeb are not suitable for this stack.

---

## How the index is built

Every indicator is converted to a **percentile rank**, so days, millimetres and index points can
be compared without assuming a normal distribution.

```
Hazard        = mean(heat, dry, wet)            heat = f(HD35, TR25)
                                               dry  = f(CDD, -WBAL)
                                               wet  = f(Rx1day, R50)

Exposure      = sum(population x heat days)     then log + percentile rank

Vulnerability = 1 - percentile rank(SHDI)

Risk          = Hazard x Exposure x Vulnerability
```

A product is used because the IPCC definition of risk requires all three parts: a hazard with
nobody exposed is not a disaster. An additive version, a PCA-weighted version and a
population-weighted-climate version are kept as robustness checks.

---

## Repository layout

```
config/config.yaml              every setting a reader might want to change
src/cro/ingest/                 boundaries, climate, population, development, probes
src/cro/features/build.py       hazard, exposure, vulnerability, risk versions
src/cro/analysis/               descriptives, hypotheses, regression, spatial statistics
src/cro/viz/                    shared theme, static maps, charts, export
src/cro/app/                    Plotly Dash dashboard + Flask summary/report routes
src/cro/db/                     PostGIS schema and idempotent loader
src/cro/report/                 report snippets + Quarto render (markdown fallback)
report/                         report.qmd (the prose) and theme.scss
tests/                          indicator maths, data contracts, presentation smoke tests
data/processed/                 all intermediate tables as Parquet
outputs/maps|figures|tables/    deliverables
outputs/report/                 report.html, validation.md, key_results.md
```

The analysis table `data/processed/region_master.parquet` is the single source every output reads
from, so maps, tables and the dashboard can never disagree with each other.

---

## Data sources and licences

| Layer | Source | Resolution | Year | Licence |
|---|---|---|---|---|
| Boundaries | [geoBoundaries](https://www.geoboundaries.org/) (gbOpen) | ADM1 polygons | 2024 release | CC-BY 4.0 |
| Climate | [NASA POWER](https://power.larc.nasa.gov/) (MERRA-2) | point daily series | 1991-2023 | Open, no key |
| Population | [GHS-POP R2023A](https://ghsl.jrc.ec.europa.eu/) | 30 arc-seconds (~1 km) | 2020 | CC-BY 4.0 |
| Subnational development | [Global Data Lab SHDI](https://globaldatalab.org/shdi/) | admin-1 | latest available | Free for research |
| National context | [World Bank WDI](https://databank.worldbank.org/source/world-development-indicators) | country | 2010-2023 | CC-BY 4.0 |

Evapotranspiration is not provided by NASA POWER, so reference ET is estimated with the
Hargreaves equation (Hargreaves & Samani, 1985) from daily maximum/minimum temperature and
latitude.

If you reuse this work, cite the sources above, not this repository alone.

---

## Reproducibility

- Every step writes Parquet to `data/processed/`, so a stage can be re-run without repeating the
  downloads.
- NASA POWER responses are cached per request, so an interrupted download resumes.
- `cro validate` checks eight data contracts (unique region ids, valid geometry, population
  reconciliation, physical ranges, index bounds, development coverage, expected tables).
- The report pulls generated tables and key numbers from the analysis output instead of
  hand-copied values, so it cannot silently go stale.
- The report renders with Quarto when available and falls back to a plain HTML build otherwise.

### Tests

```bash
pytest -q
```

- `tests/test_indicators.py` - hand-checked maths on toy data.
- `tests/test_data_contract.py` - the real files on disk (skipped before the pipeline is run).
- `tests/test_presentation.py` - geometry repair, map building, dashboard callbacks.

---

## PostGIS (optional)

```bash
docker compose up -d
cro load
```

This creates `dim_region`, `dim_country`, `fact_climate`, `fact_population`, `fact_exposure`,
`fact_development`, `fact_risk` and the view `vw_region_profile` on port **5433**. The dashboard
prefers the database and silently falls back to Parquet when it is not running, so the project
works on a laptop without Docker.

---

## Known limitations

1. **Association, not causation.** Country fixed effects absorb time-invariant national
   differences, not time-varying shocks or reverse causality.
2. **One development indicator.** SHDI does not capture inequality inside a region, which is often
   what decides who suffers in a heatwave. Subnational poverty (World Bank SPID) is the obvious
   next step.
3. **Static population.** GHS-POP 2020 is applied to a 2004-2023 climate baseline.
4. **Coarse sampling.** Up to eight points per region is adequate for Bihar and thin for Alaska;
   the count scales with area, not with climate heterogeneity.
5. **Arbitrary thresholds.** 35 C and 50 mm are defensible but they are choices; different
   thresholds give different maps.
6. **Pilot selection.** France, India and the USA were chosen to stress-test the pipeline, not to
   be representative of the world.
7. **Boundary vintage.** geoBoundaries and Global Data Lab do not always agree (Ladakh, merged
   Dadra and Nagar Haveli and Daman and Diu). Six regions have no SHDI match and are excluded from
   the development models rather than filled with a country average.

---

## Scaling to the world

Moving from 3 countries to ~150 is a configuration change:

1. Set `project.pilot_iso3` to `["ALL"]` (or list the countries you want).
2. Expect ~15,000 NASA POWER requests at up to 8 points per region: about 2 hours at 4 workers,
   plus cache storage.
3. With more than 20 countries the regression switches to country-clustered standard errors, and
   cross-border contiguity makes a single global Moran's I meaningful.

A forward-looking appendix (CMIP6 downscaled projections, SSP2-4.5 / SSP5-8.5) is deliberately
kept outside the core analysis so that measured and modelled climate are not mixed.
