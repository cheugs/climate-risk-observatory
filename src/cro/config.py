"""Read `config/config.yaml` once and hand it to the rest of the code.

Keeping settings in a YAML file means the analysis can be re-run with a
different grid size or set of countries without editing any Python.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# The project root is the folder that contains config/, src/ and data/.
# __file__ is .../src/cro/config.py, so parents[2] takes us up three levels.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


def load_config() -> dict:
    """Load the YAML config and add absolute paths.

    We return a plain dictionary rather than a class because it is easy to
    print, easy to pass around, and easy to read for someone new to the code.
    """
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Turn the relative paths in config.yaml into absolute paths.
    # This way the code works whether you run it from the project root or not.
    cfg["root"] = PROJECT_ROOT
    for key, relative in cfg["paths"].items():
        cfg["paths"][key] = PROJECT_ROOT / relative
        cfg["paths"][key].mkdir(parents=True, exist_ok=True)

    return cfg


def database_url(cfg: dict) -> str:
    """Build the SQLAlchemy connection string for PostGIS.

    Values come from .env if present, otherwise from config.yaml.
    """
    load_dotenv(PROJECT_ROOT / ".env")
    db = cfg["database"]
    user = os.getenv("DATABASE_USER", db["user"])
    password = os.getenv("DATABASE_PASSWORD", db["password"])
    host = os.getenv("DATABASE_HOST", db["host"])
    port = os.getenv("DATABASE_PORT", str(db["port"]))
    name = os.getenv("DATABASE_NAME", db["name"])
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"
