from pathlib import Path

# Repo root (financial-data-etl)
REPO_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = REPO_ROOT  # directamente el root

DB_PATH = DATA_DIR / "financial_data_etl.db"
CATALOG_PATH = DATA_DIR / "catalog.json"

LOGS_DIR = DATA_DIR / "logs"
TRACES_DIR = DATA_DIR / "ws_traces"

LOGS_DIR.mkdir(exist_ok=True)
TRACES_DIR.mkdir(exist_ok=True)