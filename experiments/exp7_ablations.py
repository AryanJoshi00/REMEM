"""Experiment 7 - ablations (spec 15.1, 15.2): which parts of the model matter?

All models are scored on the same held-out REPEAT rows of the test split. Each is compared with the full model (power-law forgetting
with the five student/concept features) by the mean difference in log loss, with a 95% student-level bootstrap interval:
  delta > 0  the variant is worse than the full model (the removed part mattered)
  delta < 0  the variant is better (the part did not help, or an extension helped)
A part "matters" only if the interval of its removal lies entirely above 0 (spec 15.4: differences inside the interval are
"not demonstrated"). Uncertainty comes from resampling students, not from refitting with other seeds: the fits are deterministic.
The extensions (offsets from Experiment 4, link feature from Experiment 9) are included when their result files exist.
The target-retention (θ) trade-off is in Experiment 6 (experiments/results/exp6_theta_sweep.csv).
Run from the repo root:  python -m experiments.exp7_ablations
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.bootstrap import cluster_bootstrap_diff, row_loss
from evaluation.metrics import evaluate
from evaluation.runlog import log_run
from experiments.exp3_forgetting import FEATS, fit_variant, predict_variant, prep
from models.links import link_feature, neighbour_weights, similarity_matrix
from models.offsets import OffsetModel
from models.stability import ALL_FEATURES, StabilityModel

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "experiments" / "results"
ART = ROOT / "artifacts"
N_BOOT = 500

LABELS = {
    "A": ("Knowledge tracing only (no forgetting)", "Forgetting"),
    "B": ("Exponential forgetting, one curve for all", "Forgetting curve"),
    "C": ("Power-law forgetting, one curve for all (no student features)", "Forgetting curve"),
    "E": ("Exponential forgetting with student features", "Forgetting curve"),
    "D-m": ("Full model without mastery", "Features"),
    "D-log_n": ("Full model without practice count", "Features"),
    "D-ability": ("Full model without student ability", "Features"),
    "D-difficulty": ("Full model without question difficulty", "Features"),
    "D-rt_z": ("Full model without response time", "Features"),
    "D+offsets": ("Full model plus concept, student and pair offsets (Experiment 4)", "Extensions"),
    "D+F": ("Full model plus recent failure on related concepts (Experiment 9)", "Extensions"),
}


def size_label(delta: float) -> str:
    """Descriptive size of a log-loss difference (a reading aid, not a decision rule): under 0.0005 negligible, under 0.002 small, else moderate."""
    a = abs(delta)
    return "negligible" if a < 0.0005 else "small" if a < 0.002 else "moderate"


def main() -> None:
    t0 = time.time()
    df = prep(pd.read_parquet(FEATS))
    rep = df[df["delta_t_days"].notna()]
    tr, te = (rep[rep["split"] == s].reset_index(drop=True) for s in ("train", "test"))
    full = StabilityModel.from_dict(json.loads((ART / "stability_model_ednet.json").read_text()))
    lam = full.lam
    print(f"repeat rows: train {len(tr):,} test {len(te):,}; lambda {lam}", flush=True)

    preds: dict[str, np.ndarray] = {"D": predict_variant(full, te), "A": te["bkt_pcorrect"].to_numpy()}
    fits = {"B": ("exp", []), "C": ("power", []), "E": ("exp", ALL_FEATURES)}
    fits.update({f"D-{f}": ("power", [x for x in ALL_FEATURES if x != f]) for f in ALL_FEATURES})
    for name, (curve, feats) in fits.items():
        preds[name] = predict_variant(fit_variant(tr, curve, feats, lam), te)
        print(f"  fitted {name} ({time.time()-t0:.0f}s)", flush=True)

    off_path = RES / "exp4_offset_summary.csv"
    if off_path.exists():
        taus = dict(pd.read_csv(off_path)[["level", "tau"]].itertuples(index=False, name=None))
        preds["D+offsets"] = OffsetModel(full).fit(tr, taus).predict(te)
        print(f"  fitted D+offsets taus={taus} ({time.time()-t0:.0f}s)", flush=True)
    sum9 = RES / "exp9_summary.json"
    if sum9.exists() and (RES / "exp9_model.json").exists():
        s9 = json.loads(sum9.read_text())
        linkm = StabilityModel.from_dict(json.loads((RES / "exp9_model.json").read_text()))
        ids = np.sort(df.loc[df["split"] == "train", "concept_id"].unique())
        W = neighbour_weights(similarity_matrix(df[df["split"] == "train"], ids), s9["k"], s9["threshold"])
        F = link_feature(df, W, ids, s9["tau_days"])
        te_F = te.assign(link_F=pd.Series(F, index=df.index).loc[rep[rep["split"] == "test"].index].to_numpy())
        preds["D+F"] = predict_variant(linkm, te_F)
        print(f"  scored D+F ({time.time()-t0:.0f}s)", flush=True)

    y = te["correct"].to_numpy()
    students = te["student_id"].to_numpy()
    loss_full = row_loss(y, preds["D"])
    rows = [{"model": "D", "label": "Full model (power-law forgetting with five student and concept features)", "group": "Reference", **evaluate(y, preds["D"]),
             "delta_logloss": 0.0, "ci_low": 0.0, "ci_high": 0.0, "verdict": "reference", "effect_size": ""}]
    for name in LABELS:
        if name not in preds:
            continue
        ci = cluster_bootstrap_diff(students, row_loss(y, preds[name]), loss_full, N_BOOT, seed=0)
        if ci["lo"] > 0:
            verdict = "worse than the full model"
        elif ci["hi"] < 0:
            verdict = "better than the full model"
        else:
            verdict = "no demonstrable difference"
        rows.append({"model": name, "label": LABELS[name][0], "group": LABELS[name][1], **evaluate(y, preds[name]),
                     "delta_logloss": ci["mean_diff"], "ci_low": ci["lo"], "ci_high": ci["hi"], "verdict": verdict, "effect_size": size_label(ci["mean_diff"])})
    out = pd.DataFrame(rows)
    out.to_csv(RES / "exp7_ablations.csv", index=False)
    pd.set_option("display.width", 220)
    print(out[["model", "logloss", "ece", "delta_logloss", "ci_low", "ci_high", "verdict"]].round(5).to_string(index=False))
    log_run("exp7_ablations", "ednet_v3", int(df.student_id.nunique()), 0, time.time() - t0,
            {"lambda": lam, "n_boot": N_BOOT, "uncertainty": "student-level bootstrap"},
            {r["model"]: {"delta": round(r["delta_logloss"], 5), "verdict": r["verdict"], "size": r["effect_size"]} for r in rows},
            "experiments/results/exp7_ablations.csv")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
