"""
Backward-compatible re-export.
All DB logic now lives in storage.database.
"""
from financial_data_etl.storage.database import get_connection, get_dict_connection
