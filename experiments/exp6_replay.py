"""Experiment 6 - scheduler replay checks (spec 15.1, 18).

On held-out REPEAT answers (test split) it asks, for two stability models:
  fitted  the EdNet-fitted global model        (artifacts/stability_model_ednet.json)
  prior   the deployed starter prior (D15)     (artifacts/stability_model.json)
 1. Calibration at recommended times: for each logged review, REMEM's recommended gap at θ = 0.85 is computed from the state
    before it; reviews are grouped by actual gap / recommended gap, and predicted vs observed correctness is compared.
 2. θ sweep: for θ in {0.75 ... 0.95} the recommended gaps, the share clipped by the safety rails, the implied reviews per
    concept-month, and how many real reviews fell near the recommendation (with predicted and observed correctness).
These checks are descriptive and judged by REMEM's own model (circular as evidence of benefit); the scheduler claim rests on
SimLab and the pilot. Poor calibration near the recommended time flags the recommendations as unreliable.
Run from the repo root:  python -m experiments.exp6_replay
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.metrics import evaluate
from evaluation.runlog import log_run
from experiments.exp3_forgetting import FEATS, prep
from models.stability import StabilityModel
from scheduler.replay import ON_TIME, THETAS, predicted_p, recommended_gap_days, stability_for, theta_sweep, timing_calibration
from scheduler.scheduler import DEFAULT_THETA

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "experiments" / "results"
ART = ROOT / "artifacts"
UNRELIABLE_ECE = 0.05                      # calibration error on reviews near the recommendation above this flags the recommendations
NEAR_BAND = (0.5, 2.0)                     # actual gap between half and twice the recommended gap
MIN_NEAR = 2000                            # fewer reviews than this near the recommendation -> "not enough evidence"
MODELS = {"fitted": "stability_model_ednet.json", "prior": "stability_model.json"}


def main() -> None:
    t0 = time.time()
    df = prep(pd.read_parquet(FEATS))
    te = df[(df["split"] == "test") & df["delta_t_days"].notna()].reset_index(drop=True)
    print(f"test repeat rows: {len(te):,}", flush=True)
    timing_rows, sweep_rows, summary = [], [], {}
    for name, fname in MODELS.items():
        mdl = StabilityModel.from_dict(json.loads((ART / fname).read_text()))
        S = stability_for(mdl, te)
        rec = recommended_gap_days(S, mdl.beta, DEFAULT_THETA)
        p = predicted_p(mdl, te)
        y = te["correct"].to_numpy(float)
        tc = timing_calibration(te["delta_t_days"], rec, p, y)
        tc.insert(0, "model", name)
        timing_rows.append(tc)
        sw = theta_sweep(mdl, te)
        sw.insert(0, "model", name)
        sweep_rows.append(sw)
        ratio = te["delta_t_days"].to_numpy(float) / rec
        on = (ratio >= ON_TIME[0]) & (ratio <= ON_TIME[1])
        near = (ratio >= NEAR_BAND[0]) & (ratio <= NEAR_BAND[1])                  # the verdict uses this wider band: more reviews, steadier estimate
        m_on = evaluate(y[on], p[on]) if on.sum() >= 50 else {"ece": float("nan")}
        m_near = evaluate(y[near], p[near]) if near.sum() >= 50 else {"ece": float("nan")}
        overall = evaluate(y, p)
        verdict = ("not enough evidence" if near.sum() < MIN_NEAR else
                   "unreliable" if (m_near["ece"] > UNRELIABLE_ECE or np.isnan(m_near["ece"])) else "calibrated near recommended times")
        summary[name] = {"beta": float(mdl.beta), "median_stability_days": float(np.median(S)), "median_recommended_gap_at_0.85": float(np.median(rec)),
                         "share_recommendations_at_max_rail": float((rec >= 180 - 1e-9).mean()), "n_on_time_reviews": int(on.sum()), "on_time_ece": float(m_on["ece"]),
                         "n_near_reviews": int(near.sum()), "near_ece": float(m_near["ece"]), "overall_ece": float(overall["ece"]),
                         "overall_logloss": float(overall["logloss"]), "verdict": verdict}
        print(f"\n== {name}: beta {mdl.beta:.3f}, median S {np.median(S):.1f} d, median recommended gap {np.median(rec):.1f} d -> {verdict}", flush=True)
        print(tc.round(3).to_string(index=False)); print(sw.round(3).to_string(index=False))
    pd.concat(timing_rows).to_csv(RES / "exp6_timing_calibration.csv", index=False)
    pd.concat(sweep_rows).to_csv(RES / "exp6_theta_sweep.csv", index=False)
    (RES / "exp6_summary.json").write_text(json.dumps(summary, indent=2))
    log_run("exp6_replay", "ednet_v3", int(df.student_id.nunique()), 0, time.time() - t0,
            {"theta": DEFAULT_THETA, "thetas": list(THETAS), "unreliable_ece": UNRELIABLE_ECE},
            {k: {"verdict": v["verdict"], "near_ece": round(v["near_ece"], 4), "n_near": v["n_near_reviews"]} for k, v in summary.items()},
            "experiments/results/exp6_summary.json")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
