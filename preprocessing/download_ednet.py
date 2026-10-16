"""Download and preprocess EdNet KT1 for REMEM.

Run from the project root:
    python preprocessing/download_ednet.py

This script follows the operations in notebooks/Remem_v1.ipynb, using paths
relative to the REMEM project rather than Google Colab's /content directory.
"""
from pathlib import Path
import os
import zipfile

import gdown
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

EDNET_ZIP = RAW / "EdNet-KT1.zip"
EDNET_DIR = RAW / "EdNet-KT1"
CONTENT_ZIP = RAW / "EdNet-content.zip"
CONTENT_DIR = RAW / "EdNet-content"

EDNET_URL = "https://drive.google.com/uc?id=1AmGcOs5U31wIIqvthn9ARqJMrMTFTcaw"
CONTENT_URL = "https://drive.google.com/uc?id=117aYJAWG3GU48suS66NPaB82HwFj6xWS"


def download_zip(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and zipfile.is_zipfile(destination):
        print(f"Using existing ZIP: {destination}")
        return
    print(f"Downloading {destination.name} ...")
    result = gdown.download(url=url, output=str(destination), quiet=False, resume=True)
    if not result or not destination.exists() or not zipfile.is_zipfile(destination):
        raise RuntimeError(
            f"Download did not produce a valid ZIP at {destination}. "
            "Check the Google Drive link/permissions and try again."
        )


def extract_zip(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    marker = destination / ".remem_extracted"
    if marker.exists():
        print(f"Using existing extraction: {destination}")
        return
    print(f"Extracting {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(destination)
    marker.touch()
    print(f"Extracted to: {destination}")


def find_kt1_dir() -> Path:
    candidates = [EDNET_DIR / "KT1", EDNET_DIR]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.csv")):
            return candidate
    for candidate in EDNET_DIR.rglob("KT1"):
        if candidate.is_dir() and any(candidate.glob("*.csv")):
            return candidate
    raise FileNotFoundError(
        f"Could not find EdNet KT1 user CSVs under {EDNET_DIR}. "
        "Inspect the extracted archive layout."
    )


def find_questions_csv() -> Path:
    candidates = [
        CONTENT_DIR / "contents" / "questions.csv",
        CONTENT_DIR / "questions.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    matches = list(CONTENT_DIR.rglob("questions.csv"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Could not find questions.csv under {CONTENT_DIR}")


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)

    # Notebook Steps 1-9: download/extract EdNet interaction and content data.
    download_zip(EDNET_URL, EDNET_ZIP)
    extract_zip(EDNET_ZIP, EDNET_DIR)
    data_dir = find_kt1_dir()

    download_zip(CONTENT_URL, CONTENT_ZIP)
    extract_zip(CONTENT_ZIP, CONTENT_DIR)
    questions_path = find_questions_csv()

    # Notebook Steps 6-7: use the first 100 sorted student files as a manageable sample.
    csv_files = sorted(data_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No user CSV files found in {data_dir}")
    sample_files = csv_files[:100]
    frames = []
    for file_path in sample_files:
        frame = pd.read_csv(file_path)
        frame["student_id"] = file_path.stem
        frames.append(frame)
    sample_data = pd.concat(frames, ignore_index=True)
    sample_path = PROCESSED / "ednet_sample.csv"
    sample_data.to_csv(sample_path, index=False)
    print(f"EdNet users sampled: {len(sample_files)}")
    print(f"EdNet sample interactions: {len(sample_data):,}")
    print(f"Saved: {sample_path}")

    # Notebook Step 11: merge question metadata and derive correctness.
    questions = pd.read_csv(questions_path)
    required_question_cols = {"question_id", "correct_answer", "part", "tags"}
    missing = required_question_cols - set(questions.columns)
    if missing:
        raise ValueError(f"EdNet questions metadata is missing columns: {sorted(missing)}")
    questions = questions[
        ["question_id", "correct_answer", "part", "tags"]
    ].drop_duplicates(subset=["question_id"])

    merged = sample_data.merge(
        questions, on="question_id", how="left", validate="many_to_one"
    )
    user_answer = merged["user_answer"].astype("string").str.strip().str.lower()
    correct_answer = merged["correct_answer"].astype("string").str.strip().str.lower()
    matched = user_answer.notna() & correct_answer.notna()
    merged["correct"] = pd.Series(pd.NA, index=merged.index, dtype="Int8")
    merged.loc[matched, "correct"] = (
        user_answer[matched] == correct_answer[matched]
    ).astype("int8")
    with_correct_path = PROCESSED / "ednet_sample_with_correct.csv"
    merged.to_csv(with_correct_path, index=False)
    print(f"Saved: {with_correct_path}")
    print(f"Rows with matched answers: {int(matched.sum()):,}")

    # Notebook Step 13: clean interactions and sort by student/time.
    clean = merged.dropna(
        subset=["student_id", "question_id", "user_answer", "correct"]
    ).copy()
    clean["correct"] = clean["correct"].astype("int8")
    clean["timestamp"] = pd.to_numeric(clean["timestamp"], errors="coerce")
    clean["elapsed_time"] = pd.to_numeric(clean["elapsed_time"], errors="coerce")
    clean = clean.dropna(subset=["timestamp", "elapsed_time"])
    clean = clean.sort_values(["student_id", "timestamp"]).reset_index(drop=True)
    clean_path = PROCESSED / "ednet_clean.csv"
    clean.to_csv(clean_path, index=False)
    print(f"Clean EdNet interactions: {len(clean):,}")
    print(f"Saved: {clean_path}")

    # Notebook Steps 15-17: question-to-tag and question-to-KC mappings.
    question_tags = (
        clean[["question_id", "tags"]]
        .dropna(subset=["tags"])
        .drop_duplicates()
        .assign(tag_id=lambda frame: frame["tags"].astype(str).str.split(";"))
        .explode("tag_id")
    )
    question_tags["tag_id"] = question_tags["tag_id"].str.strip()
    question_tags = (
        question_tags[["question_id", "tag_id"]]
        .drop_duplicates()
        .sort_values(["question_id", "tag_id"])
        .reset_index(drop=True)
    )
    tags_path = PROCESSED / "ednet_question_tags.csv"
    question_tags.to_csv(tags_path, index=False)
    print(f"Saved: {tags_path}")

    components = (
        question_tags[question_tags["tag_id"] != "-1"]
        .drop_duplicates()
        .rename(columns={"tag_id": "knowledge_component_id"})
        .sort_values(["question_id", "knowledge_component_id"])
        .reset_index(drop=True)
    )
    components_path = PROCESSED / "ednet_knowledge_components.csv"
    components.to_csv(components_path, index=False)
    print(f"Saved: {components_path}")

    # Notebook Step 18: write a compact dataset summary.
    summary = {
        "total_interactions": len(clean),
        "unique_students": clean["student_id"].nunique(),
        "unique_questions": clean["question_id"].nunique(),
        "correct_interactions": int((clean["correct"] == 1).sum()),
        "incorrect_interactions": int((clean["correct"] == 0).sum()),
        "unique_knowledge_components": components["knowledge_component_id"].nunique(),
        "question_component_associations": len(components),
    }
    summary_df = pd.DataFrame(list(summary.items()), columns=["metric", "value"])
    summary_path = PROCESSED / "ednet_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"Saved: {summary_path}")
    print("\nEdNet preprocessing completed.")


if __name__ == "__main__":
    main()
