"""Experiment 9 - concept-linked failure feature F (spec 9.5, 15.1, H4).

Question: does a recent failure on a related concept help predict the next answer on this concept once the memory model is
fitted? Related concepts come from a co-error correlation computed on the TRAIN split only; F decays exponentially with time.

The model is the EdNet-fitted memory model (power curve, features m, log_n, ability, difficulty, rt_z) refitted WITH link_F as
one more feature, and compared with the same model without it on held-out REPEAT rows of the test split.
Settings (neighbours k, correlation threshold, decay tau_F) are chosen on the validation split from a small grid.
The decision rule was fixed before the run: F is kept only if the 95% student-level bootstrap interval of the log-loss gain on the
test split lies above zero; otherwise it is reported as "not demonstrated" and dropped from the product.
Controls (added after the first run showed a larger gain than expected, so that the result can be read correctly): the same feature built
with the links shuffled across concepts (three shuffles) and with every concept equally linked to every other. The gain is called
"specific to related concepts" only if the real links beat every control with a 95% interval above zero; otherwise F is read as a
general measure of recent failures, not of related concepts.
Run from the repo root:  python -m experiments.exp9_concept_link
"""
from __future__ import annotations

import json
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.bootstrap import cluster_bootstrap_diff, row_loss
from evaluation.metrics import evaluate
from evaluation.runlog import log_run
from experiments.exp3_forgetting import FEATS, prep
from models.links import link_feature, neighbour_weights, similarity_matrix
from models.stability import ALL_FEATURES, StabilityModel

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "experiments" / "results"
ART = ROOT / "artifacts"
GRID_K = (5, 15)
THRESHOLD = 0.05
GRID_TAU = (1.0, 7.0)                       # days
N_BOOT = 500


def predict(model: StabilityModel, d: pd.DataFrame) -> np.ndarray:
    X = d[model.features].to_numpy(float)
    return model.predict(d["delta_t_days"].to_numpy(float), X, d["m"].to_numpy(float), d["guess"].to_numpy(float), d["slip"].to_numpy(float))


def fit(tr: pd.DataFrame, feats: list[str], lam: float) -> StabilityModel:
    X = tr[feats].to_numpy(float)
    return StabilityModel(features=feats, curve="power", lam=lam).fit(tr["delta_t_days"].to_numpy(float), X, tr["m"].to_numpy(float),
                                                                      tr["guess"].to_numpy(float), tr["slip"].to_numpy(float), tr["correct"].to_numpy(float))


def main() -> None:
    t0 = time.time()
    df = prep(pd.read_parquet(FEATS))
    base = StabilityModel.from_dict(json.loads((ART / "stability_model_ednet.json").read_text()))
    lam = base.lam
    ids = np.sort(df.loc[df["split"] == "train", "concept_id"].unique())
    corr = similarity_matrix(df[df["split"] == "train"], ids)
    print(f"concepts {len(ids)}; similarity pairs above {THRESHOLD}: {int((corr > THRESHOLD).sum()):,} ({time.time()-t0:.0f}s)", flush=True)

    rows, best = [], None
    for k, tau in product(GRID_K, GRID_TAU):
        W = neighbour_weights(corr, k, THRESHOLD)
        d = df.assign(link_F=link_feature(df, W, ids, tau))
        rep = d[d["delta_t_days"].notna()]
        tr, va = rep[rep["split"] == "train"], rep[rep["split"] == "val"]
        mdl = fit(tr, ALL_FEATURES + ["link_F"], lam)
        ll = evaluate(va["correct"], predict(mdl, va))["logloss"]
        rows.append({"k": k, "tau_days": tau, "val_logloss": ll, "w_link_F": float(mdl.w[-1])})
        print(f"  k={k:<3} tau={tau:<4} val logloss {ll:.5f}  w_F {mdl.w[-1]:+.4f} ({time.time()-t0:.0f}s)", flush=True)
        if best is None or ll < best["ll"]:
            best = {"ll": ll, "k": k, "tau": tau, "W": W, "model": mdl, "F": d["link_F"].to_numpy()}
    base_val = evaluate(df[(df["split"] == "val") & df["delta_t_days"].notna()]["correct"], predict(base, df[(df["split"] == "val") & df["delta_t_days"].notna()]))["logloss"]
    pd.DataFrame(rows).assign(base_val_logloss=base_val).to_csv(RES / "exp9_grid.csv", index=False)

    d = df.assign(link_F=best["F"])
    te = d[(d["split"] == "test") & d["delta_t_days"].notna()].reset_index(drop=True)
    link = best["model"]
    p_base, p_link = predict(base, te), predict(link, te)
    out = []
    for subset, mask in (("repeats", np.ones(len(te), bool)), ("spaced>=1d", te["delta_t_days"].to_numpy() >= 1.0),
                         ("recent failure elsewhere (F>0.1)", te["link_F"].to_numpy() > 0.1), ("no recent related failure (F<=0.1)", te["link_F"].to_numpy() <= 0.1)):
        for name, p in (("without F (global model)", p_base), ("with F", p_link)):
            out.append({"subset": subset, "model": name, **evaluate(te["correct"].to_numpy()[mask], p[mask])})
    pd.DataFrame(out).to_csv(RES / "exp9_overall.csv", index=False)

    y = te["correct"].to_numpy()
    la, lb = row_loss(y, p_base), row_loss(y, p_link)
    ci = cluster_bootstrap_diff(te["student_id"].to_numpy(), la, lb, N_BOOT, seed=0)
    spaced = te["delta_t_days"].to_numpy() >= 1.0
    ci_spaced = cluster_bootstrap_diff(te["student_id"].to_numpy()[spaced], la[spaced], lb[spaced], N_BOOT, seed=0)
    w5 = float(link.w[-1])
    F = te["link_F"].to_numpy()

    # ---- controls: does the gain depend on WHICH concepts are linked?
    ctrl_rows, ctrl_worse_than_real = [], []
    n_c = len(ids)
    uniform = (np.ones((n_c, n_c)) - np.eye(n_c)) * (best["W"].sum(1).mean() / (n_c - 1))
    controls = [(f"shuffled links (seed {sd})", best["W"][np.ix_(*(2 * [np.random.default_rng(sd).permutation(n_c)]))]) for sd in (0, 1, 2)]
    controls.append(("every concept equally linked", uniform))
    for name, Wc in controls:
        dc = df.assign(link_F=link_feature(df, Wc, ids, best["tau"]))
        repc = dc[dc["delta_t_days"].notna()]
        mc = fit(repc[repc["split"] == "train"], ALL_FEATURES + ["link_F"], lam)
        tec = repc[repc["split"] == "test"].reset_index(drop=True)
        lc = row_loss(tec["correct"].to_numpy(), predict(mc, tec))
        vs_base = cluster_bootstrap_diff(te["student_id"].to_numpy(), la, lc, N_BOOT, seed=0)            # gain of the control over the global model
        real_vs = cluster_bootstrap_diff(te["student_id"].to_numpy(), lc, lb, N_BOOT, seed=0)             # control loss - real-link loss (positive = real links better)
        ctrl_rows.append({"control": name, "w_link_F": float(mc.w[-1]), "gain_over_global": vs_base["mean_diff"], "gain_lo": vs_base["lo"], "gain_hi": vs_base["hi"],
                          "real_links_better_by": real_vs["mean_diff"], "better_lo": real_vs["lo"], "better_hi": real_vs["hi"], "logloss": float(lc.mean())})
        ctrl_worse_than_real.append(real_vs["lo"] > 0)
        print(f"  control {name}: gain {vs_base['mean_diff']:+.5f}; real links better by {real_vs['mean_diff']:+.5f} [{real_vs['lo']:+.5f}, {real_vs['hi']:+.5f}] ({time.time()-t0:.0f}s)", flush=True)
    pd.DataFrame(ctrl_rows).to_csv(RES / "exp9_controls.csv", index=False)
    specific = bool(all(ctrl_worse_than_real))

    # most strongly linked neighbours, for the report
    nb = []
    for i, c in enumerate(ids):
        for j in np.argsort(-corr[i])[:3]:
            if corr[i, j] > THRESHOLD:
                nb.append({"concept": int(c), "neighbour": int(ids[j]), "correlation": float(corr[i, j])})
    pd.DataFrame(nb).to_csv(RES / "exp9_top_neighbours.csv", index=False)
    verdict = ("not demonstrated; dropped from the product" if ci["lo"] <= 0 else
               "supported, specific to related concepts" if specific else "supported, but not specific to related concepts (reads as a general recent-failure signal)")
    summary = {"k": best["k"], "tau_days": best["tau"], "threshold": THRESHOLD, "w_link_F": w5, "effect_on_log_S_at_F_p90": float(w5 * np.percentile(F[F > 0], 90)) if (F > 0).any() else 0.0,
               "share_rows_F_above_0.1": float((F > 0.1).mean()), "n_test_rows": int(len(te)),
               "logloss_gain_overall": ci, "logloss_gain_spaced_1d": ci_spaced, "specific_to_related_concepts": specific, "verdict": verdict, "base_val_logloss": base_val, "link_val_logloss": best["ll"]}
    (RES / "exp9_summary.json").write_text(json.dumps(summary, indent=2))
    (RES / "exp9_model.json").write_text(json.dumps({**link.to_dict(), "k": best["k"], "tau_days": best["tau"], "threshold": THRESHOLD}, indent=2))

    print("\nTEST:", json.dumps(summary, indent=1))
    log_run("exp9_concept_link", "ednet_v3", int(df.student_id.nunique()), 0, time.time() - t0,
            {"grid_k": list(GRID_K), "grid_tau_days": list(GRID_TAU), "threshold": THRESHOLD, "n_boot": N_BOOT},
            {"w_link_F": round(w5, 4), "gain": round(ci["mean_diff"], 6), "ci": [round(ci["lo"], 6), round(ci["hi"], 6)], "verdict": verdict},
            "experiments/results/exp9_summary.json")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
