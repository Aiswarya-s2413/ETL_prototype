# extractors/api_extractor.py
import requests, pandas as pd

def extract_from_api(url: str, params: dict = None, field_map: dict = None) -> pd.DataFrame:
    print(f"[API] Calling: {url}")
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if isinstance(data, dict):
            for key in ["products", "data", "items", "results"]:
                if key in data:
                    data = data[key]
                    break

        df = pd.DataFrame(data)

        # Rename fields from API to match Django model
        if field_map and not df.empty:
            df = df.rename(columns=field_map)

        expected = ["name", "description", "unit_of_measurement", "price", "category"]
        if not df.empty:
            df = df[[c for c in expected if c in df.columns]]
            print(f"[API] {len(df)} records extracted.")
        return df
    except Exception as e:
        print(f"[API] API request failed: {e}")
        return pd.DataFrame()
