"""Experiment 10 - SimLab: reviews needed at matched true retention, with mis-specified generators (spec 16).

For each generator (gen1 matched, gen2/gen3 mis-specified) and seed:
  1. fit REMEM's stability model on a training cohort simulated under a neutral random-interval schedule;
  2. sweep each policy's knob (REMEM theta, fixed interval, SM-2 interval multiplier) on a fresh evaluation cohort;
  3. find the fixed/SM-2 knob whose mean true recall at review matches REMEM(theta=0.85) and compare review counts.
Findings concern simulated learners only.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, wilcoxon

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.runlog import log_run  # noqa: E402
from models.stability import StabilityModel  # noqa: E402
from simlab import sim  # noqa: E402

OUT = ROOT / "experiments" / "results"
N_EVAL, N_CONCEPTS = 200, 8
SEEDS = [0, 1, 2]
THETAS = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
FIXED = [1, 2, 3, 5, 7, 10, 14]
SM2_MULT = [0.5, 0.75, 1.0, 1.5, 2.0]


def summarise(res: sim.Result) -> dict:
    return {"reviews_per_concept": float(res.reviews_per_concept.mean()), "recall_at_review": float(res.recall_at_review.mean()),
            "frac_below_target": float(res.frac_below.mean()), "final_recall": float(np.nanmean(res.final_recall))}


MATCH_ON = {                  # metric used to equalise "retention"; higher knob = longer intervals = worse on each
    "below_target": lambda r: float(r.frac_below.mean()),          # share of time true recall < 0.85 (primary: coverage over time)
    "final_recall": lambda r: -float(np.nanmean(r.final_recall)),   # delayed-test recall at the horizon (secondary)
}


def match(coh, gen, phi, seed, make_policy, lo, hi, target, metric):
    """Bisection on a monotone knob so `metric` equals the REMEM(theta=0.85) value (lower metric = better retention)."""
    f = MATCH_ON[metric]
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        if f(sim.simulate(coh, make_policy(mid), gen, phi=phi, seed=seed)) < target:
            lo = mid
        else:
            hi = mid
    knob = 0.5 * (lo + hi)
    return knob, sim.simulate(coh, make_policy(knob), gen, phi=phi, seed=seed)


def run_one(gen: str, seed: int, phi: float, prior: StabilityModel):
    model = sim.fit_remem_model(gen, seed, phi=phi)
    model_global = sim.fit_remem_model(gen, seed, phi=phi, features=())
    coh = sim.Cohort(N_EVAL, N_CONCEPTS, seed=seed)
    rows = []

    def add(policy, knob, res):
        rows.append({"gen": gen, "seed": seed, "phi": phi, "policy": policy, "knob": knob, **summarise(res)})

    remem_res = {}
    for th in THETAS:
        pol = sim.RememPolicy(model, th, "remem")
        res = sim.simulate(coh, pol, gen, phi=phi, seed=seed)
        add("remem", th, res); remem_res[th] = (res, pol)
    for th in (0.85,):
        add("remem_global", th, sim.simulate(coh, sim.RememPolicy(model_global, th, "remem_global"), gen, phi=phi, seed=seed))
        add("remem_prior", th, sim.simulate(coh, sim.RememPolicy(prior, th, "remem_prior"), gen, phi=phi, seed=seed))
    for d in FIXED:
        add("fixed", d, sim.simulate(coh, sim.FixedPolicy(d), gen, phi=phi, seed=seed))
    for mlt in SM2_MULT:
        add("sm2", mlt, sim.simulate(coh, sim.SM2Policy(mlt), gen, phi=phi, seed=seed))

    # matched-retention comparison against REMEM(theta=0.85)
    ref_res, ref_pol = remem_res[0.85]
    matched = []
    for metric, name, mk, lo, hi in [(mt, nm, mk_, lo_, hi_) for mt in MATCH_ON for nm, mk_, lo_, hi_ in
                                     (("fixed", lambda k: sim.FixedPolicy(k), 1.0, 40.0), ("sm2", lambda k: sim.SM2Policy(k), 0.2, 4.0))]:
        target = MATCH_ON[metric](ref_res)
        knob, res = match(coh, gen, phi, seed, mk, lo, hi, target, metric)
        d = ref_res.reviews_per_concept - res.reviews_per_concept
        try:
            p = float(wilcoxon(d).pvalue) if np.any(d != 0) else 1.0
        except ValueError:
            p = 1.0
        matched.append({"gen": gen, "seed": seed, "phi": phi, "matched_on": metric, "baseline": name, "matched_knob": knob,
                        "target_value": target, "remem_recall": float(ref_res.recall_at_review.mean()), "baseline_recall": float(res.recall_at_review.mean()),
                        "remem_reviews": float(ref_res.reviews_per_concept.mean()), "baseline_reviews": float(res.reviews_per_concept.mean()),
                        "reviews_saved_pct": 100 * (1 - ref_res.reviews_per_concept.mean() / res.reviews_per_concept.mean()),
                        "remem_below": float(ref_res.frac_below.mean()), "baseline_below": float(res.frac_below.mean()),
                        "remem_final": float(np.nanmean(ref_res.final_recall)), "baseline_final": float(np.nanmean(res.final_recall)),
                        "wilcoxon_p_reviews": p})
    est = ref_res.s_true_hat
    rho = float(spearmanr(est[:, 0], est[:, 1]).statistic) if est is not None and len(est) > 10 else np.nan
    rec = {"gen": gen, "seed": seed, "phi": phi, "spearman_S": rho, "beta_fit": float(model.beta), "w": json.dumps([round(float(x), 3) for x in model.w])}
    return rows, matched, rec


def main():
    t0 = time.time()
    prior = StabilityModel.from_dict(json.loads((ROOT / "artifacts" / "stability_model.json").read_text()))
    F, M, R = [], [], []
    configs = [(g, 1.5) for g in ("gen1", "gen2", "gen3")] + [("gen1", 0.5), ("gen1", 3.0)]     # phi sweep on the matched generator
    for gen, phi in configs:
        for seed in SEEDS:
            f, m, r = run_one(gen, seed, phi, prior)
            F += f; M += m; R.append(r)
            print(f"{gen} phi={phi} seed={seed}: " + "; ".join(f"{x['matched_on'][:5]}/{x['baseline']} {x['reviews_saved_pct']:.0f}%" for x in m), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(F).to_csv(OUT / "exp10_frontier.csv", index=False)
    md = pd.DataFrame(M); md.to_csv(OUT / "exp10_matched.csv", index=False)
    pd.DataFrame(R).to_csv(OUT / "exp10_recovery.csv", index=False)
    agg = md.groupby(["gen", "phi", "matched_on", "baseline"]).agg(saved_mean=("reviews_saved_pct", "mean"), saved_min=("reviews_saved_pct", "min"),
                                                       saved_max=("reviews_saved_pct", "max")).reset_index()
    print(agg.to_string(index=False))
    log_run("exp10_simlab", "simlab", N_EVAL, 0, time.time() - t0,
            {"seeds": SEEDS, "concepts": N_CONCEPTS, "horizon_days": sim.HORIZON_DAYS, "configs": configs},
            {f"{r.gen}_phi{r.phi}_{r.matched_on}_{r.baseline}_saved_mean": round(float(r.saved_mean), 2) for r in agg.itertuples()},
            "experiments/results/exp10_matched.csv")


if __name__ == "__main__":
    main()
