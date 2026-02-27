from fastapi import FastAPI
from financial_data_etl.api.db import get_connection
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="financial-data-etl api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"status": "api ok"}

@app.get("/symbols")
def get_symbols():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM tv_candles_raw ORDER BY symbol"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()