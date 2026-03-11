# config/settings.py

# ── Target DB (Django's PostgreSQL) ──────────────────────────────
DB_URL = "postgresql+psycopg2://etl_user:etl_password@localhost:5434/etl_db"

# ── Source File Paths ─────────────────────────────────────────────
CSV_FILE_PATH  = "sample_data/products.csv"
JSON_FILE_PATH = "sample_data/products.json"

# ── REST API Source ───────────────────────────────────────────────
API_URL    = "https://your-api.com/products"
API_PARAMS = {"limit": 100}

# ── Source Database ───────────────────────────────────────────────
SOURCE_DB_URL   = "mysql+pymysql://user:pass@host:3306/source_db"
SOURCE_DB_QUERY = """
    SELECT name, description, unit_of_measurement, price, category
    FROM raw_products
"""

# ── Target Table (Django's table name) ────────────────────────────
TARGET_TABLE = "api_product"   # Django names it: appname_modelname

# ── Ollama / DeepSeek Config ──────────────────────────────────────
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "deepseek-r1:7b"

# ── Valid Categories ──────────────────────────────────────────────
VALID_CATEGORIES = [
    "Fruits", "Vegetables", "Dairy", "Grains",
    "Bakery", "Beverages", "Meat", "Seafood", "Other"
]
