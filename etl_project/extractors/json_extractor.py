# extractors/json_extractor.py
import pandas as pd, json

def extract_from_json(file_path: str) -> pd.DataFrame:
    print(f"[JSON] Reading: {file_path}")
    try:
        with open(file_path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("products", list(data.values())[0])
        df = pd.DataFrame(data)
        expected = ["name", "description", "unit_of_measurement", "price", "category"]
        df = df[[c for c in expected if c in df.columns]]
        print(f"[JSON] {len(df)} records extracted.")
        return df
    except Exception as e:
        print(f"[JSON] Error reading {file_path}: {e}")
        return pd.DataFrame()
