from pathlib import Path
import json
import os

# Raíz total del repositorio
REPO_ROOT = Path(__file__).resolve().parents[2]

# Directorio del paquete (financial_data_etl) - Nivel 1
PACKAGE_DIR = Path(__file__).resolve().parents[1]

# Storage local general
DATA_DIR = REPO_ROOT 

DB_PATH = Path(
    os.getenv("FORGE_DB_PATH", DATA_DIR / "financial_data_etl.db")
)

# Ahora apunta a la carpeta padre de storage
CATALOG_PATH = PACKAGE_DIR / "catalog.json"

LOGS_DIR = DATA_DIR / "logs"
TRACES_DIR = DATA_DIR / "ws_traces"

LOGS_DIR.mkdir(exist_ok=True)
TRACES_DIR.mkdir(exist_ok=True)

PRIVATE_CONFIG_PATH = REPO_ROOT / "private_config.json"

if PRIVATE_CONFIG_PATH.exists():
    with open(PRIVATE_CONFIG_PATH, "r") as f:
        PRIVATE_CONFIG = json.load(f)
else:
    PRIVATE_CONFIG = None