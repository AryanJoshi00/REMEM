"""Download and preprocess ASSISTments for REMEM.

Run from the project root:
    python preprocessing/download_assistments.py
"""
from pathlib import Path

import gdown
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "assistments"
PROCESSED = ROOT / "data" / "processed"
FILE_ID = "1NNXHFRxcArrU0ZJSb9BIL56vmUt5FhlE"
RAW_FILE = RAW / "assistments_skill_builder_2009_2010.csv"
OUTPUT_FILE = PROCESSED / "assistments_clean.csv"


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    if RAW_FILE.exists() and RAW_FILE.stat().st_size > 0:
        print(f"Using existing dataset: {RAW_FILE}")
    else:
        url = f"https://drive.google.com/uc?id={FILE_ID}"
        result = gdown.download(url, str(RAW_FILE), quiet=False)
        if not result or not RAW_FILE.exists() or RAW_FILE.stat().st_size == 0:
            raise RuntimeError(
                "ASSISTments download failed. Check the Google Drive link/permissions."
            )
        print(f"Downloaded: {RAW_FILE}")
        print(f"File size: {RAW_FILE.stat().st_size / (1024 ** 2):.2f} MB")

    assistments = pd.read_csv(RAW_FILE, encoding="cp1252", low_memory=False)
    print("Raw dataset shape:", assistments.shape)

    required = {
        "user_id", "problem_id", "correct", "order_id", "sequence_id",
        "skill_id", "skill_name", "attempt_count", "hint_count", "ms_first_response"
    }
    missing = required - set(assistments.columns)
    if missing:
        raise ValueError(f"ASSISTments source is missing required columns: {sorted(missing)}")

    clean = assistments.rename(columns={
        "user_id": "student_id",
        "problem_id": "question_id",
        "skill_id": "knowledge_component_id",
        "skill_name": "knowledge_component_name",
    })
    clean = clean[
        [
            "student_id", "question_id", "correct", "order_id", "sequence_id",
            "knowledge_component_id", "knowledge_component_name",
            "attempt_count", "hint_count", "ms_first_response",
        ]
    ].copy()

    clean["correct"] = pd.to_numeric(clean["correct"], errors="coerce")
    clean = clean[clean["correct"].isin([0, 1])].copy()
    clean["correct"] = clean["correct"].astype("int8")
    clean = clean.sort_values(["student_id", "order_id"]).reset_index(drop=True)
    clean.to_csv(OUTPUT_FILE, index=False)

    # Re-read saved file and validate it, following notebook Step 23.
    check = pd.read_csv(OUTPUT_FILE, low_memory=False)
    print("\nClean dataset saved:", OUTPUT_FILE)
    print("Total interactions:", len(check))
    print("Unique students:", check["student_id"].nunique())
    print("Unique questions:", check["question_id"].nunique())
    print("Unique knowledge components:", check["knowledge_component_id"].nunique())
    print("Missing student IDs:", check["student_id"].isna().sum())
    print("Missing question IDs:", check["question_id"].isna().sum())
    print("Missing correctness:", check["correct"].isna().sum())
    print("Invalid correctness values:", (~check["correct"].isin([0, 1])).sum())
    print("Duplicate rows:", check.duplicated().sum())
    print("\nCorrectness distribution:")
    print(check["correct"].value_counts().sort_index())
    print("\nASSISTments preprocessing completed.")


if __name__ == "__main__":
    main()
