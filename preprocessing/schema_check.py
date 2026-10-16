"""Validate the dataset schemas produced by REMEM preprocessing scripts.

Run from the project root:
    python preprocessing/schema_check.py
"""
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"

EDNET_FILE = PROCESSED / "ednet_clean.csv"
EDNET_COMPONENTS_FILE = PROCESSED / "ednet_knowledge_components.csv"
ASSISTMENTS_FILE = PROCESSED / "assistments_clean.csv"

EDNET_REQUIRED = [
    "student_id", "question_id", "timestamp", "correct", "elapsed_time", "tags"
]
EDNET_COMPONENTS_REQUIRED = ["question_id", "knowledge_component_id"]
ASSISTMENTS_REQUIRED = [
    "student_id", "question_id", "correct", "order_id", "sequence_id",
    "knowledge_component_id", "knowledge_component_name", "attempt_count",
    "hint_count", "ms_first_response"
]


def check_file(path: Path, required_columns: list[str], label: str) -> bool:
    print(f"\n=== {label} ===")
    if not path.exists():
        print(f"✗ FILE NOT FOUND: {path}")
        return False

    df = pd.read_csv(path, nrows=5)
    print(f"File: {path}")
    print("Columns:")
    for column in required_columns:
        status = "✓" if column in df.columns else "✗ MISSING"
        print(f"  {column}: {status}")

    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        print(f"Schema FAILED. Missing columns: {missing}")
        return False
    print("Schema PASSED")
    return True


def main() -> None:
    checks = [
        check_file(EDNET_FILE, EDNET_REQUIRED, "EdNet cleaned interactions"),
        check_file(
            EDNET_COMPONENTS_FILE,
            EDNET_COMPONENTS_REQUIRED,
            "EdNet knowledge-component mapping",
        ),
        check_file(ASSISTMENTS_FILE, ASSISTMENTS_REQUIRED, "ASSISTments cleaned data"),
    ]
    if not all(checks):
        print("\nOne or more schema checks FAILED.")
        sys.exit(1)
    print("\nAll schema checks PASSED.")


if __name__ == "__main__":
    main()
