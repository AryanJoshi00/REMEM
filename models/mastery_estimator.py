from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "ednet_clean.csv"
OUTPUT = ROOT / "data" / "processed" / "mastery_scores.csv"


def main():
    df = pd.read_csv(DATA)

    df["correct"] = pd.to_numeric(df["correct"], errors="coerce")
    df = df.dropna(subset=["student_id", "question_id", "correct"])

    # Estimate performance per student and question
    mastery = (
        df.groupby(["student_id", "question_id"])["correct"]
        .agg(["mean", "count"])
        .reset_index()
    )

    mastery["mastery_score"] = (mastery["mean"] * 100).round(2)
    mastery["revision_priority"] = (
        100 - mastery["mastery_score"]
    ).round(2)

    mastery.to_csv(OUTPUT, index=False)

    print(f"Interactions analysed: {len(df):,}")
    print(f"Student-question pairs: {len(mastery):,}")
    print(f"Saved results: {OUTPUT}")
    print("\nSample results:")
    print(mastery.head(10).to_string(index=False))


if __name__ == "__main__":
    main()