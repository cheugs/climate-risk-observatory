# Small image that serves the dashboard, the summary and the report.
# The analysis pipeline is not run here: the app only reads the finished
# tables in data/processed and outputs.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/src \
    PORT=7860

WORKDIR /app

# Dependencies first, so Docker can cache this layer between code changes.
COPY requirements-deploy.txt ./
RUN pip install --no-cache-dir -r requirements-deploy.txt

# Only the files the app reads at runtime.
COPY config ./config
COPY src ./src
COPY data/processed/dashboard_regions.parquet ./data/processed/dashboard_regions.parquet
COPY outputs/tables ./outputs/tables
COPY outputs/maps ./outputs/maps
COPY outputs/report ./outputs/report

EXPOSE 7860

# app.py reads PORT from the environment, so the same image works locally,
# on Render (PORT=10000) and on a Hugging Face Space (PORT=7860).
CMD ["python", "-m", "cro.app.app"]
