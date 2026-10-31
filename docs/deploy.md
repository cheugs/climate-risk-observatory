# Deploying the observatory for free

The production deployment lives at
<https://climate-risk-observatory.onrender.com> (Render free plan, service
`climate-risk-observatory`, blueprint `render.yaml`). Pushing to `main` on
GitHub redeploys it automatically. The notes below explain how it was set up
and what to do if you want to move it.

The app is a normal Flask server (Dash is mounted on it), so it needs a host
that can run Python continuously. It does **not** need PostGIS, Docker, or the
raw data: the dashboard reads the small simplified table in
`data/processed/dashboard_regions.parquet`, and the summary and report read
`outputs/tables` and `outputs/report`.

What actually has to be uploaded:

| Path | Size | Why |
|---|---|---|
| `src/` + `config/` | < 1 MB | the application |
| `data/processed/dashboard_regions.parquet` | 0.6 MB | the dashboard data |
| `outputs/tables/*.csv` | < 1 MB | summary page numbers |
| `outputs/maps/map_web_*.html` | 6.3 MB | the interactive maps linked from the report |
| `outputs/report/report(.fr).html` + `.pdf` | 19 MB | the written report, both languages |
| `requirements-deploy.txt` | < 1 KB | runtime packages only |

Everything else (`data/raw`, `data/cache`, most of `data/processed`,
`outputs/figures`, the static map PNGs, `.venv`) is excluded by `.gitignore`
and `.dockerignore`. A full checkout is about 27 MB, not the 1 GB of working
data.

The app reads `PORT` from the environment and binds to `0.0.0.0`, so the same
code works locally, on Render, and in a container.

---

## Option A - Render, free plan (recommended)

Render still offers a genuinely free web service. No payment method is needed
to start; if you exceed the monthly included usage they suspend the free
service instead of billing you. As of 2026 the free plan is **0.1 CPU / 512 MB
RAM**, spins down after **15 minutes** without traffic, and wakes on the next
request in about a minute.

The app uses about **180 MB** while serving the dashboard (measured in the
Docker image), so 512 MB is comfortable. The slow part is the 0.1 CPU: map
callbacks take a few seconds instead of under one.

### 1. Put the code on GitHub

From the project folder:

```powershell
git init
git add .
git commit -m "Climate Risk & Human Development Observatory"
git branch -M main
git remote add origin https://github.com/YOUR-NAME/climate-risk-observatory.git
git push -u origin main
```

Check that the dashboard table was included:

```powershell
git ls-files data/processed
# data/processed/dashboard_regions.parquet
```

If it is missing, the `.gitignore` exception did not apply; run
`git add -f data/processed/dashboard_regions.parquet` once.

The GitHub repository can be public or private. Render can read private repos
through its GitHub app.

### 2. Create the Render service

1. Sign in at <https://dashboard.render.com> with GitHub.
2. Click **New +** and choose **Blueprint**.
3. Pick the repository. Render reads `render.yaml` and shows one free web
   service called `climate-risk-observatory`.
4. Click **Apply** (or **Create**).

If you prefer to configure it by hand instead of using the blueprint:

- **Runtime:** Python 3
- **Build command:** `pip install -r requirements-deploy.txt`
- **Start command:** `python -m cro.app.app`
- **Environment variables:** `PYTHONPATH=src`, `PYTHON_VERSION=3.12.10`
- **Plan:** Free

The first build takes a few minutes because it downloads pandas, GeoPandas,
Plotly and the rest. The logs should end with:

```
dashboard: loaded simplified geometry cache
dashboard: running on http://127.0.0.1:10000 (bound to 0.0.0.0)
```

### 3. Open the URLs

Render gives you `https://climate-risk-observatory.onrender.com` (the exact
name depends on your service name):

- `/` - dashboard
- `/summary` - the reading page
- `/report` - the full HTML report
- `/report.pdf` - the PDF
- `/summary?lang=fr`, `/report/fr`, `/report/fr.pdf` - the French versions
- `/maps/map_web_risk.html` - the interactive maps (also `hazard`, `exposure`, `shdi`)

Every page has an EN / FR switch in the header; the choice is kept in a
`cro_lang` cookie.

The first visit after a quiet period takes about a minute while Render starts
the service. That is normal on the free plan.

### Free-plan limits to know

- 750 free instance hours per month. A service that sleeps when idle uses far
  fewer than that.
- The service sleeps after 15 minutes without requests. The next visitor waits
  about a minute.
- 512 MB RAM and 0.1 CPU. The app fits in memory; it is just slower than local.
- Files written at runtime are lost on restart. This app only reads its data,
  so nothing is lost.
- If you run out of included bandwidth or build minutes, Render suspends the
  free service until the next month instead of charging you (when no card is
  attached).

---

## Option B - your own computer + Cloudflare Tunnel

Completely free, no account limits, but your computer has to stay on. Good for
a demo, a presentation, or a link you only need for a few days.

1. Start the app locally: `cro app` (or `python -m cro.app.app`).
2. Install `cloudflared` (Windows: `winget install --id Cloudflare.cloudflared`).
3. Run a quick tunnel:

   ```powershell
   cloudflared tunnel --url http://localhost:8050
   ```

4. It prints a public `https://....trycloudflare.com` URL that forwards to
   your machine. The URL changes each time you restart the tunnel.

For a stable URL, create a free Cloudflare account, add a domain, and create a
named tunnel instead. The app itself does not change.

---

## Option C - static summary and report only

If you only need the written material online, the summary and the report are
plain HTML and can be hosted for free on GitHub Pages, Netlify or Cloudflare
Pages. They never sleep and need no server.

1. Export the summary once:

   ```powershell
   python -c "from cro.app.summary import build_summary_html; open('summary.html','w',encoding='utf-8').write(build_summary_html())"
   ```

2. Put `summary.html`, `outputs/report/report.html` and `report.pdf` in a
   folder with `assets/style.css` and `assets/summary.css`.
3. Edit the two `<link href="/assets/...">` lines in `summary.html` to
   `assets/...`, and change the dashboard links (they point to `/`) to your
   Render URL or remove them.
4. Publish the folder with GitHub Pages, Netlify Drop, or Cloudflare Pages.

This is not the interactive observatory, but it costs nothing and never sleeps.

---

## Other free hosts, and why they do not fit

- **Hugging Face Spaces:** Docker and Gradio Spaces now require a paid PRO
  plan to create. Free accounts can only create Static Spaces, which cannot
  run Dash.
- **PythonAnywhere:** free and no card, but the Beginner plan has a **512 MB
  disk quota** and this stack installs about **830 MB** of packages. It fits
  only if you prune dependencies heavily or upgrade.
- **Koyeb, Fly.io, Railway:** no free compute tier for new accounts any more.
- **Vercel / Netlify functions:** the serverless response limit is 4.5 MB.
  The Dash layout alone is about 7.8 MB and the report is 6.7 MB, so the
  dashboard and the report would fail.
- **Google Cloud Run / Oracle Always Free:** generous free allowances, but
  both require a credit card for identity verification.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'cro'`**
The start command runs from the repository root. Set `PYTHONPATH=src` (the
blueprint already does).

**The dashboard loads but the maps are empty**
Check that `data/processed/dashboard_regions.parquet` is in the deployed repo
(`git ls-files data/processed`). The app uses the cache when the full
`region_master.parquet` is absent.

**Build runs out of memory**
Use the Dockerfile instead of the native Python runtime, or build with
`pip install --no-cache-dir -r requirements-deploy.txt`. The runtime footprint
is small; the build is the memory-heavy step.

**Render spins down and the first visit is slow**
Expected on the free plan. Hit `/summary` first: it is a light page and wakes
the service before the heavier dashboard.

**I changed the code**
Commit and push to GitHub. Render redeploys automatically.
