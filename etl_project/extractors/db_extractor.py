# extractors/db_extractor.py
import pandas as pd
from sqlalchemy import create_engine, text

def extract_from_database(db_url: str, query: str) -> pd.DataFrame:
    print(f"[DB] Connecting to source database...")
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        print(f"[DB] {len(df)} records extracted.")
        return df
    except Exception as e:
        print(f"[DB] Error connecting to database: {e}")
        return pd.DataFrame()
