import subprocess
from pathlib import Path

#🔧 PASO 1 — Requisitos previos (fuera del código)
#Antes de escribir nada:
#Tener un VPS.
#Tener acceso SSH funcionando con key (NO password).
#Saber:
#user
#host
#path remoto donde vive la DB (ej: /app/data/financial_data_etl.db)
#Ejemplo real:
#leonardo@123.45.67.89:/app/data/financial_data_etl.db
#Sin eso configurado, nada automatiza.

def run_sync_db_to_server(db_path: str) -> None:
    """
    Sync local SQLite DB to remote server via SCP.
    Fase 1: simple file replacement.
    """

    local_path = Path(db_path)

    if not local_path.exists():
        raise FileNotFoundError(f"DB not found at {local_path}")

    # ===== CONFIGURACIÓN FASE 1 =====
    REMOTE_USER = "YOUR_USER"
    REMOTE_HOST = "YOUR_SERVER_IP"
    REMOTE_PATH = "/app/data/financial_data_etl.db"
    # =================================

    remote_target = f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_PATH}"

    print(f"[SYNC] Uploading {local_path} → {remote_target}")

    result = subprocess.run(
        ["scp", str(local_path), remote_target],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("[SYNC ERROR]")
        print(result.stderr)
        raise RuntimeError("Database sync failed.")

    print("[SYNC] Completed successfully.")