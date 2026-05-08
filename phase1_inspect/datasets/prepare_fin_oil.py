"""
Build fin_oil_prompts.csv from fin_oil_dataset.xlsx for Phase 1 Inspect labs.

Run from phase1_inspect/:
    python datasets/prepare_fin_oil.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).parent
XLSX_PATH = SCRIPT_DIR / "fin_oil_dataset.xlsx"
OUT_DIR = SCRIPT_DIR / "fin_oil"
OUT_CSV = OUT_DIR / "fin_oil_prompts.csv"

SHEET = 0  # «Лист1»
COL_CATEGORY = "Категория"
COL_PROMPT = "Промпт"


def main() -> None:
    if not XLSX_PATH.is_file():
        raise SystemExit(f"Missing source file: {XLSX_PATH}")

    df = pd.read_excel(XLSX_PATH, sheet_name=SHEET)
    if COL_PROMPT not in df.columns or COL_CATEGORY not in df.columns:
        raise SystemExit(
            f"Expected columns {COL_CATEGORY!r} and {COL_PROMPT!r}, got {list(df.columns)}"
        )

    df = df.copy()
    df["_cat_ff"] = df[COL_CATEGORY].ffill()
    df = df.dropna(subset=[COL_PROMPT])
    df[COL_PROMPT] = df[COL_PROMPT].astype(str).str.strip()
    df = df[df[COL_PROMPT] != ""]
    df["_cat_ff"] = df["_cat_ff"].fillna("").astype(str).str.strip()

    out = pd.DataFrame(
        {
            "prompt": df[COL_PROMPT],
            "category": df["_cat_ff"],
        }
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8")
    print(f"Wrote {len(out)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
