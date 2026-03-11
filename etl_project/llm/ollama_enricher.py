# llm/ollama_enricher.py
import requests
import json
from config.settings import OLLAMA_URL, OLLAMA_MODEL

def enrich_description(name: str, category: str) -> str:
    """Use DeepSeek to generate a product description if missing."""
    prompt = f"""You are a product data assistant.
Write a short 1-sentence product description for:
Product name: {name}
Category: {category}
Reply with only the description. No preamble."""

    try:
        response = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }, timeout=15)
        return response.json().get("response", "").strip()
    except Exception as e:
        print(f"Error enriching description for {name}: {e}")
        return ""


def classify_category(name: str, valid_categories: list) -> str:
    """Use DeepSeek to assign the correct category."""
    categories_str = ", ".join(valid_categories)
    prompt = f"""You are a product classification assistant.
Given the product name: "{name}"
Choose the single most appropriate category from this list: {categories_str}
Reply with only the category name. Nothing else."""

    try:
        response = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }, timeout=15)
        result = response.json().get("response", "Other").strip()
        return result if result in valid_categories else "Other"
    except Exception as e:
        print(f"Error classifying category for {name}: {e}")
        return "Other"


def standardize_unit(unit: str) -> str:
    """Use DeepSeek to normalize unit of measurement."""
    prompt = f"""You are a data normalization assistant.
Standardize this unit of measurement to a clean, lowercase standard form:
Input: "{unit}"
Examples: "KG" -> "kg", "Liter" -> "litre", "pcs" -> "piece"
Reply with only the standardized unit. Nothing else."""

    try:
        response = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }, timeout=15)
        return response.json().get("response", unit).strip().lower()
    except Exception as e:
        print(f"Error standardizing unit for {unit}: {e}")
        return unit.lower()
