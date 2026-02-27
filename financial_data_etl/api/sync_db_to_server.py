import subprocess
from pathlib import Path
import sqlite3
from financial_data_etl.storage.paths import PRIVATE_CONFIG

def run_sync_db_to_server(db_path: str, ctx) -> None:
    """
    Sync local SQLite DB to remote server via SCP.
    Strategy:
      1) Create a consistent snapshot using VACUUM INTO (no WAL dependency)
      2) SCP snapshot to remote .tmp
      3) Atomic mv on server: .tmp -> final
    """

    local_db = Path(db_path)
    if not local_db.exists():
        raise FileNotFoundError(f"DB not found at {local_db}")

    # ===== CONFIGURACIÓN FASE 1 =====
    if PRIVATE_CONFIG is None:
        raise RuntimeError("private_config.json not found.")

    REMOTE_USER = PRIVATE_CONFIG["remote_user"]
    REMOTE_HOST = PRIVATE_CONFIG["remote_host"]
    REMOTE_PATH_FINAL = PRIVATE_CONFIG["remote_path"]
    REMOTE_PATH_TMP = REMOTE_PATH_FINAL + ".tmp"
    SCP_EXE = PRIVATE_CONFIG["scp_exe"]
    SSH_EXE = PRIVATE_CONFIG["ssh_exe"]
    # =================================

    # 1) Build a consistent snapshot file locally
    snapshot_path = local_db.with_suffix(local_db.suffix + ".snapshot")
    if snapshot_path.exists():
        snapshot_path.unlink()

    # IMPORTANT: VACUUM INTO writes a complete, consistent DB file
    conn = sqlite3.connect(str(local_db))
    try:
        conn.execute("VACUUM INTO ?", (str(snapshot_path),))
    finally:
        conn.close()

    ctx.event(
        "db_snapshot_created",
        stage="db_sync",
        snapshot_size_bytes=snapshot_path.stat().st_size,
    )

    # 2) Upload snapshot to remote tmp
    remote_target_tmp = f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_PATH_TMP}"

    scp_result = subprocess.run(
        [SCP_EXE, str(snapshot_path), remote_target_tmp],
        capture_output=True,
        text=True,
    )
    if scp_result.returncode != 0:
        ctx.event(
            "db_sync_scp_failed",
            level="ERROR",
            stage="db_sync",
            stderr=scp_result.stderr,
        )
        raise RuntimeError("Database sync failed (scp).")
    
    ctx.event(
        "db_snapshot_uploaded",
        stage="db_sync",
        return_code=scp_result.returncode,
    )

    # 3) Atomic swap on server
    mv_cmd = f"mv -f {REMOTE_PATH_TMP} {REMOTE_PATH_FINAL}"
    ssh_result = subprocess.run(
        [SSH_EXE, f"{REMOTE_USER}@{REMOTE_HOST}", mv_cmd],
        capture_output=True,
        text=True,
    )
    if ssh_result.returncode != 0:
        ctx.event(
            "db_sync_mv_failed",
            level="ERROR",
            stage="db_sync",
            stderr=ssh_result.stderr,
        )
        raise RuntimeError("Database sync failed (remote mv).")
    
    ctx.event(
        "db_atomic_swap_completed",
        stage="db_sync",
        return_code=ssh_result.returncode,
    )