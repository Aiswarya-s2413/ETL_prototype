# transformers/product_transformer.py
import pandas as pd
from llm.ollama_enricher import enrich_description, classify_category, standardize_unit
from config.settings import VALID_CATEGORIES

def transform(df: pd.DataFrame, source_label: str = "unknown", use_llm: bool = True) -> pd.DataFrame:
    print(f"[Transformer] Processing {len(df)} records from '{source_label}'")

    if df.empty:
        return df

    # ── 1. Ensure all columns exist ──────────────────────────────
    for col in ["name", "description", "unit_of_measurement", "price", "category"]:
        if col not in df.columns:
            df[col] = None

    # ── 2. Drop rows with missing name ───────────────────────────
    before = len(df)
    df = df[df["name"].notna() & (df["name"].astype(str).str.strip() != "")]
    if len(df) < before:
        print(f"[Transformer] Dropped {before - len(df)} rows with missing name.")

    if df.empty:
        return df

    # ── 3. Normalize text ─────────────────────────────────────────
    df["name"]                 = df["name"].astype(str).str.strip().str.title()
    df["category"]             = df["category"].astype(str).str.strip().str.title()
    df["unit_of_measurement"]  = df["unit_of_measurement"].astype(str).str.strip().str.lower()

    # ── 4. Normalize price ────────────────────────────────────────
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.00)
    df["price"] = df["price"].round(2)

    # ── 5. LLM Enrichment (DeepSeek via Ollama) ───────────────────
    if use_llm:
        print("[Transformer] Running LLM enrichment via DeepSeek...")
        for i, row in df.iterrows():

            # Auto-fill empty descriptions
            if pd.isna(row["description"]) or str(row["description"]).strip() in ["", "nan", "None"]:
                print(f"  → Generating description for: {row['name']}")
                df.at[i, "description"] = enrich_description(row["name"], row["category"])

            # Validate/correct category
            valid_set = {c.lower() for c in VALID_CATEGORIES}
            if str(row["category"]).lower() not in valid_set:
                print(f"  → Classifying category for: {row['name']}")
                df.at[i, "category"] = classify_category(row["name"], VALID_CATEGORIES)

            # Standardize unit
            known_units = {"kg", "g", "litre", "ml", "piece", "dozen", "box", "pack", "unit", "loaf"}
            if str(row["unit_of_measurement"]) not in known_units:
                print(f"  → Standardizing unit for: {row['name']} (was: {row['unit_of_measurement']})")
                df.at[i, "unit_of_measurement"] = standardize_unit(row["unit_of_measurement"])

    # ── 6. Fill remaining nulls ───────────────────────────────────
    df["description"]         = df["description"].fillna("N/A")
    df["unit_of_measurement"] = df["unit_of_measurement"].replace({"none": "unit", "nan": "unit", "": "unit"})

    # ── 7. Remove duplicates (by name within source) ─────────────
    before = len(df)
    df = df.drop_duplicates(subset=["name", "category"], keep="first")
    if len(df) < before:
        print(f"[Transformer] Removed {before - len(df)} duplicate items.")

    print(f"[Transformer] {len(df)} clean records ready.")
    return df[["name", "description", "unit_of_measurement", "price", "category"]]
