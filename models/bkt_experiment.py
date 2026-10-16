from pathlib import Path
import pandas as pd
from pyBKT.models import Model

def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "data" / "processed" / "ednet_clean.csv"
    mapping_path = root / "data" / "processed" / "ednet_knowledge_components.csv"

    df = pd.read_csv(source, nrows=300)
    mapping = pd.read_csv(mapping_path)

    df["question_id"] = df["question_id"].astype(str)
    mapping["question_id"] = mapping["question_id"].astype(str)

    df = df.merge(mapping, on="question_id", how="inner")
    df = df.drop_duplicates(["student_id", "question_id", "timestamp"])

    if df.empty:
        print("No matching interactions. Stopping safely.")
        return

    df["user_id"] = df["student_id"].astype(str)
    df["skill_name"] = df["knowledge_component_id"].astype(str)
    df["correct"] = df["correct"].astype(int)
    df = df.sort_values(["user_id", "skill_name", "timestamp"])
    df["order_id"] = df.groupby(["user_id", "skill_name"]).cumcount()

    data = df[["user_id", "skill_name", "correct", "order_id"]].copy()

    print(f"Testing on {len(data)} interactions...")
    model = Model(seed=42)
    model.fit(data=data, parallel=False, num_fits=1)

    output = root / "data" / "processed" / "bkt_predictions.csv"
    predictions = model.predict(data=data)
    predictions.to_csv(output, index=False)
    print(f"Success. Predictions saved to {output}")

if __name__ == "__main__":
    main()