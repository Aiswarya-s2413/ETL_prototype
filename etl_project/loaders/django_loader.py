# loaders/django_loader.py
import pandas as pd
from sqlalchemy import create_engine, text

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS api_product (
    id                   SERIAL PRIMARY KEY,
    name                 VARCHAR(255) NOT NULL,
    description          TEXT,
    unit_of_measurement  VARCHAR(50),
    price                NUMERIC(15, 2),
    category             VARCHAR(100),
    CONSTRAINT unique_name_category UNIQUE (name, category)
);
"""

UPSERT_SQL = """
INSERT INTO api_product (name, description, unit_of_measurement, price, category)
VALUES (:name, :description, :unit_of_measurement, :price, :category)
ON CONFLICT (name, category) DO UPDATE SET
    description         = EXCLUDED.description,
    unit_of_measurement = EXCLUDED.unit_of_measurement,
    price               = EXCLUDED.price;
"""

def load_to_django_db(df: pd.DataFrame, db_url: str) -> None:
    if df.empty:
        print("[Loader] No data to load.")
        return

    print(f"[Loader] Connecting to PostgreSQL...")
    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute(text(CREATE_TABLE_SQL))
            conn.commit()

            for _, row in df.iterrows():
                conn.execute(text(UPSERT_SQL), row.to_dict())
            conn.commit()

        print(f"[Loader] ✅ {len(df)} records loaded into api_product.")
    except Exception as e:
        print(f"[Loader] Error loading to DB: {e}")
