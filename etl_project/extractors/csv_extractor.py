# extractors/csv_extractor.py
import pandas as pd

def extract_from_csv(file_path: str) -> pd.DataFrame:
    print(f"[CSV] Reading: {file_path}")
    try:
        df = pd.read_csv(file_path)
        print(f"[CSV] {len(df)} records extracted.")
        return df
    except Exception as e:
        print(f"[CSV] Error reading {file_path}: {e}")
        return pd.DataFrame()
