from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "ednet_clean.csv"
OUTPUT = ROOT / "data" / "processed" / "revision_schedule.csv"


def main():
    df = pd.read_csv(DATA)
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df["correct"] = pd.to_numeric(df["correct"], errors="coerce")
    df = df.dropna(subset=["student_id", "question_id", "timestamp", "correct"])

    # Aggregate attempts for each student and question
    grouped = (
        df.sort_values("timestamp")
        .groupby(["student_id", "question_id"])
        .agg(
            mastery=("correct", "mean"),
            attempts=("correct", "count"),
            last_seen=("timestamp", "max"),
        )
        .reset_index()
    )

    # Convert epoch milliseconds to datetime
    grouped["last_seen"] = pd.to_datetime(grouped["last_seen"], unit="ms", utc=True)

    # Calculate elapsed time since each question was last attempted
    now = pd.Timestamp.now(tz="UTC")
    grouped["days_since_review"] = (
        (now - grouped["last_seen"]).dt.total_seconds() / 86400
    ).clip(lower=0)

    # Priority increases with low mastery and time since review
    grouped["priority_score"] = (
        (1 - grouped["mastery"]) * 70
        + (grouped["days_since_review"] / 7).clip(upper=1) * 30
    ).round(2)

    grouped["recommended_action"] = grouped["mastery"].apply(
        lambda x: "Relearn" if x < 0.5 else
        "Practice" if x < 0.8 else "Quick revision"
    )

    schedule = grouped.sort_values("priority_score", ascending=False)
    schedule.to_csv(OUTPUT, index=False)

    print(f"Revision items generated: {len(schedule):,}")
    print(f"Saved schedule: {OUTPUT}")
    print("\nTop 10 revision priorities:")
    print(schedule.head(10).to_string(index=False))


if __name__ == "__main__":
    main()