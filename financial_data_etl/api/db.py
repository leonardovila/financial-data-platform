import sqlite3
from financial_data_etl.storage.paths import DB_PATH

def get_connection():
    return sqlite3.connect(DB_PATH)

