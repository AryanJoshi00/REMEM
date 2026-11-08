"""Experiment 1 - dataset feasibility (spec §15, gate G1).

Question: does the sampled EdNet data contain enough multi-day same-concept repeats,
and does accuracy actually vary with the gap? Writes CSVs + a figure to experiments/results/.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "ednet_v3.parquet"
RES = ROOT / "experiments" / "results"
MS_H, MS_D = 3_600_000, 86_400_000


def main() -> None:
    RES.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(DATA)
    df = df.sort_values(["student_id", "concept_id", "timestamp"], kind="mergesort")
    key = ["student_id", "concept_id"]
    df["gap_days"] = df.groupby(key)["timestamp"].diff() / MS_D
    # session counter: new session when gap > 30 min
    new_sess = (df["gap_days"].isna()) | (df["gap_days"] > 30 / 1440)
    df["session_idx"] = new_sess.groupby([df.student_id, df.concept_id]).cumsum()
    df["prior_sessions"] = df["session_idx"] - 1  # sessions strictly before the current one when new session

    rep = df.dropna(subset=["gap_days"]).copy()
    out = {"students": int(df.student_id.nunique()), "rows": int(len(df)), "concepts": int(df.concept_id.nunique()),
           "same_concept_repeat_pairs": int(len(rep))}
    for label, d in [(">1h", 1 / 24), (">1d", 1), (">3d", 3), (">7d", 7), (">30d", 30)]:
        out[f"repeats_gap{label}"] = int((rep.gap_days > d).sum())
        out[f"share_gap{label}"] = round(float((rep.gap_days > d).mean()), 4)
    sp = df.groupby("student_id")["timestamp"].agg(lambda x: (x.max() - x.min()) / MS_D)
    out["student_span_days_median"] = round(float(sp.median()), 1)
    out["student_span_days_p90"] = round(float(sp.quantile(0.9)), 1)
    seq = df.groupby("student_id").size()
    out["interactions_per_student_median"] = int(seq.median())
    out["overall_accuracy"] = round(float(df.correct.mean()), 4)
    spaced_students = rep[rep.gap_days >= 1].groupby("student_id").size()
    out["students_with_>=5_spaced_repeats(>=1d)"] = int((spaced_students >= 5).sum())
    pc = rep[rep.gap_days >= 1].groupby("concept_id").size()
    out["concepts_with_>=200_spaced_repeats"] = int((pc >= 200).sum())

    # raw accuracy and accuracy-above-student-mean by gap bin (quantile-free, interpretable edges in days)
    edges = [0, 1 / 1440 * 5, 1 / 24, 6 / 24, 1, 3, 7, 14, 30, 90, 1e9]
    labels = ["<5m", "5m-1h", "1h-6h", "6h-1d", "1-3d", "3-7d", "7-14d", "14-30d", "30-90d", ">90d"]
    rep["bin"] = pd.cut(rep.gap_days, edges, labels=labels, include_lowest=True)
    stud_mean = df.groupby("student_id")["correct"].mean().rename("stud_mean")
    rep = rep.join(stud_mean, on="student_id")
    rep["resid"] = rep["correct"] - rep["stud_mean"]
    tab = rep.groupby("bin", observed=True).agg(n=("correct", "size"), accuracy=("correct", "mean"), resid_vs_student_mean=("resid", "mean")).reset_index()
    tab.to_csv(RES / "exp1_accuracy_by_gap.csv", index=False)
    (RES / "exp1_summary.json").write_text(json.dumps(out, indent=2))
    pd.DataFrame({"n_sessions": df.groupby(key)["session_idx"].max()}).describe().to_csv(RES / "exp1_sessions_per_pair.csv")

    fig, ax = plt.subplots(1, 3, figsize=(15, 4))
    ax[0].hist(np.log10(rep.gap_days.clip(lower=1e-4)), bins=60); ax[0].set_xlabel("log10 gap (days) between same-concept attempts"); ax[0].set_ylabel("pairs")
    ax[1].hist(sp.clip(upper=400), bins=60); ax[1].set_xlabel("student active span (days, capped 400)"); ax[1].set_ylabel("students")
    ax[2].bar(tab.bin.astype(str), tab.accuracy); ax[2].set_xlabel("gap bin"); ax[2].set_ylabel("accuracy on repeat"); ax[2].tick_params(axis="x", rotation=60)
    plt.tight_layout(); plt.savefig(RES / "exp1_gaps.png", dpi=130)

    print(json.dumps(out, indent=2)); print(tab.to_string(index=False))


if __name__ == "__main__":
    main()
