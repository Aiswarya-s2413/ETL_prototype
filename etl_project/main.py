# main.py
import argparse
import pandas as pd
import sys
import os

# Ensure Python can find our modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.settings import (
    DB_URL, CSV_FILE_PATH, JSON_FILE_PATH,
    API_URL, API_PARAMS, SOURCE_DB_URL, SOURCE_DB_QUERY
)
from extractors.csv_extractor  import extract_from_csv
from extractors.json_extractor import extract_from_json
from extractors.api_extractor  import extract_from_api
from extractors.db_extractor   import extract_from_database
from transformers.product_transformer import transform
from loaders.django_loader     import load_to_django_db

def run_pipeline(sources: list, use_llm: bool = True):
    all_frames = []

    # ── EXTRACT ──────────────────────────────────────────────────
    print("\n== STAGE 1: EXTRACT ==")

    if "csv" in sources:
        df = extract_from_csv(CSV_FILE_PATH)
        if not df.empty: all_frames.append(("csv", df))

    if "json" in sources:
        df = extract_from_json(JSON_FILE_PATH)
        if not df.empty: all_frames.append(("json", df))

    if "api" in sources:
        df = extract_from_api(API_URL, params=API_PARAMS)
        if not df.empty: all_frames.append(("api", df))

    if "db" in sources:
        df = extract_from_database(SOURCE_DB_URL, SOURCE_DB_QUERY)
        if not df.empty: all_frames.append(("db", df))

    if not all_frames:
        print("No data extracted. Exiting.")
        return

    # ── TRANSFORM ─────────────────────────────────────────────────
    print("\n== STAGE 2: TRANSFORM + LLM ENRICHMENT ==")
    transformed = []
    for label, df in all_frames:
        # Pass a copy to avoid SettingWithCopyWarning
        t_df = transform(df.copy(), source_label=label, use_llm=use_llm)
        if not t_df.empty:
            transformed.append(t_df)

    if not transformed:
        print("No valid data after transform. Exiting.")
        return

    combined = pd.concat(transformed, ignore_index=True)
    combined = combined.drop_duplicates(subset=["name", "category"], keep="first")

    print(f"\nFinal record count: {len(combined)}")
    print(combined.to_string(index=False))

    # ── LOAD ──────────────────────────────────────────────────────
    print("\n== STAGE 3: LOAD ==")
    load_to_django_db(combined, DB_URL)

    print("\n✅ ETL PIPELINE COMPLETE")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", nargs="+",
                        choices=["csv", "json", "api", "db"],
                        default=["csv", "json", "api", "db"])
    parser.add_argument("--no-llm", action="store_true",
                        help="Skip LLM enrichment (faster, for testing)")
    args = parser.parse_args()
    
    # Use LLM by default unless --no-llm is specified
    run_pipeline(args.source, use_llm=not args.no_llm)
