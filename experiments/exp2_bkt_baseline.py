"""Experiment 2 - BKT baseline vs simple baselines on the chronological split (spec 14, 15).

Gate G1 check: BKT must beat the majority baseline and the pipeline must run without leakage.
Run from the repo root:  python -m experiments.exp2_bkt_baseline
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from baselines import simple
from evaluation.metrics import evaluate
from evaluation.runlog import log_run
from models.bkt_pipeline import fit_all, filter_all
from preprocessing.features import add_causal_features, chronological_split, fit_train_stats

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "ednet_v3.parquet"
OUT = ROOT / "data" / "processed" / "features_v3.parquet"
RES = ROOT / "experiments" / "results"
SEED = 1


def main() -> None:
    t0 = time.time()
    df = pd.read_parquet(DATA)
    df, c_train, c_val = chronological_split(df)
    st = fit_train_stats(df, c_train, c_val)
    print("split sizes:", df["split"].value_counts().to_dict())
    df = add_causal_features(df, st)
    print(f"features built ({time.time()-t0:.0f}s); fitting BKT per concept on train rows ...")
    params, pooled = fit_all(df, seed=SEED)
    df = filter_all(df, params, pooled)
    print(f"BKT done ({time.time()-t0:.0f}s)")

    df.to_parquet(OUT, index=False)
    (ROOT / "data" / "processed" / "bkt_params.json").write_text(json.dumps(
        {"pooled": vars(pooled), "by_concept": {str(c): vars(p) for c, p in params.items()}}, indent=2))

    rows = []
    for split in ("val", "test"):
        d = df[df["split"] == split]
        for subset, dd in (("all", d), ("spaced>=1d", d[d["delta_t_days"] >= 1.0])):
            preds = {
                "majority": simple.majority(dd, st.global_acc),
                "student_accuracy": simple.student_accuracy(dd),
                "concept_difficulty": simple.concept_difficulty(dd),
                "bkt_no_forgetting": dd["bkt_pcorrect"].to_numpy(),
            }
            for name, p in preds.items():
                m = evaluate(dd["correct"], p)
                rows.append({"split": split, "subset": subset, "model": name, **m})
    res = pd.DataFrame(rows)
    res.to_csv(RES / "exp2_baselines.csv", index=False)
    pd.set_option("display.width", 200)
    print(res.round(4).to_string(index=False))

    test_all = res[(res.split == "test") & (res.subset == "all")].set_index("model")
    log_run("exp2_bkt_baseline", "ednet_v3", int(df.student_id.nunique()), SEED, time.time() - t0,
            {"split": "70/15/15 chronological", "bkt_fit_cap": 40}, test_all[["auc", "logloss", "ece"]].round(4).to_dict("index"),
            "experiments/results/exp2_baselines.csv")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
