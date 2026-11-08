"""Experiment 3 (+ ablation preview of Experiment 7) - forgetting calibration (spec 15).

Compares, on held-out REPEAT interactions (rows with an earlier interaction on the same concept):
  A  BKT, no forgetting
  B  BKT + one global exponential decay
  C  BKT + one global power-law decay
  D  BKT + feature-driven power-law stability   (REMEM)
  E  BKT + feature-driven exponential stability
plus ablations of D (drop one feature at a time).
Run from the repo root:  python -m experiments.exp3_forgetting
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from evaluation.metrics import evaluate
from evaluation.runlog import log_run
from models.stability import ALL_FEATURES, StabilityModel

ROOT = Path(__file__).resolve().parents[1]
FEATS = ROOT / "data" / "processed" / "features_v3.parquet"
BKT_JSON = ROOT / "data" / "processed" / "bkt_params.json"
RES = ROOT / "experiments" / "results"
ART = ROOT / "artifacts"
SEED = 1
GAP_EDGES = [0, 5 / 1440, 1 / 24, 0.25, 1, 3, 7, 14, 30, 90, 1e9]
GAP_LABELS = ["<5m", "5m-1h", "1h-6h", "6h-1d", "1-3d", "3-7d", "7-14d", "14-30d", "30-90d", ">90d"]


def prep(df: pd.DataFrame) -> pd.DataFrame:
    bp = json.loads(BKT_JSON.read_text())
    G = {int(c): v["G"] for c, v in bp["by_concept"].items()}
    S = {int(c): v["S"] for c, v in bp["by_concept"].items()}
    df = df.copy()
    df["guess"] = df["concept_id"].map(G).fillna(bp["pooled"]["G"])
    df["slip"] = df["concept_id"].map(S).fillna(bp["pooled"]["S"])
    df["m"] = df["bkt_prior"]
    df["log_n"] = np.log1p(df["n_sessions"])
    df["difficulty"] = df["concept_difficulty"]
    return df


def matrices(d: pd.DataFrame, feats: list[str]):
    X = d[feats].to_numpy(float) if feats else np.zeros((len(d), 0))
    return d["delta_t_days"].to_numpy(float), X, d["m"].to_numpy(float), d["guess"].to_numpy(float), d["slip"].to_numpy(float), d["correct"].to_numpy(float)


def fit_variant(tr, curve, feats, lam):
    dt, X, m, g, s, y = matrices(tr, feats)
    return StabilityModel(features=feats, curve=curve, lam=lam).fit(dt, X, m, g, s, y)


def predict_variant(model: StabilityModel, d):
    dt, X, m, g, s, _ = matrices(d, model.features)
    return model.predict(dt, X, m, g, s)


def main() -> None:
    t0 = time.time()
    df = prep(pd.read_parquet(FEATS))
    rep = df[df["delta_t_days"].notna()]
    tr, va, te = (rep[rep["split"] == s] for s in ("train", "val", "test"))
    print(f"repeat rows: train {len(tr):,}  val {len(va):,}  test {len(te):,}")

    models: dict[str, StabilityModel | None] = {"A_bkt_no_forgetting": None}
    print("fitting B, C (global S)...")
    models["B_exp_global"] = fit_variant(tr, "exp", [], 1e-3)
    models["C_power_global"] = fit_variant(tr, "power", [], 1e-3)

    best_lam, best_ll, best_model = None, 9, None
    for lam in (1e-4, 1e-3, 1e-2):
        mdl = fit_variant(tr, "power", ALL_FEATURES, lam)
        ll = evaluate(va["correct"], predict_variant(mdl, va))["logloss"]
        print(f"  D lambda={lam}: val logloss {ll:.5f} ({time.time()-t0:.0f}s)")
        if ll < best_ll:
            best_lam, best_ll, best_model = lam, ll, mdl
    models["D_power_features(REMEM)"] = best_model
    models["E_exp_features"] = fit_variant(tr, "exp", ALL_FEATURES, best_lam)
    for f in ALL_FEATURES:
        models[f"D_minus_{f}"] = fit_variant(tr, "power", [x for x in ALL_FEATURES if x != f], best_lam)
    print(f"all fits done ({time.time()-t0:.0f}s), lambda={best_lam}")

    rows, cal_rows = [], []
    for split, d in (("val", va), ("test", te)):
        for subset, dd in (("repeats", d), ("spaced>=1d", d[d["delta_t_days"] >= 1.0])):
            for name, mdl in models.items():
                p = dd["bkt_pcorrect"].to_numpy() if mdl is None else predict_variant(mdl, dd)
                rows.append({"split": split, "subset": subset, "model": name, **evaluate(dd["correct"], p)})
    # calibration by gap bin on test repeats
    bins = pd.cut(te["delta_t_days"], GAP_EDGES, labels=GAP_LABELS, include_lowest=True)
    for name, mdl in models.items():
        if name.startswith("D_minus"):
            continue
        p = te["bkt_pcorrect"].to_numpy() if mdl is None else predict_variant(mdl, te)
        t = pd.DataFrame({"bin": bins.to_numpy(), "p": p, "y": te["correct"].to_numpy()}).groupby("bin", observed=True).agg(n=("y", "size"), observed=("y", "mean"), predicted=("p", "mean")).reset_index()
        t["abs_gap"] = (t["observed"] - t["predicted"]).abs()
        t.insert(0, "model", name)
        cal_rows.append(t)

    res = pd.DataFrame(rows); cal = pd.concat(cal_rows)
    res.to_csv(RES / "exp3_forgetting_metrics.csv", index=False)
    cal.to_csv(RES / "exp3_calibration_by_gap.csv", index=False)

    D = models["D_power_features(REMEM)"]
    coef = pd.DataFrame({"term": ["intercept"] + D.features, "w": D.w})
    coef.to_csv(RES / "exp3_coefficients.csv", index=False)
    ART.mkdir(exist_ok=True)
    (ART / "stability_model_ednet.json").write_text(json.dumps(D.to_dict(), indent=2))
    bp = json.loads(BKT_JSON.read_text())
    (ART / "bkt_params.json").write_text(json.dumps(bp))

    pd.set_option("display.width", 220)
    show = res[(res.split == "test")].pivot_table(index="model", columns="subset", values=["logloss", "auc", "ece"]).round(4)
    print(show.to_string())
    print("\nREMEM coefficients (log S = w0 + ...):"); print(coef.round(3).to_string(index=False)); print("beta =", round(D.beta, 3))
    print("\nTest calibration by gap (A vs D):")
    for nm in ("A_bkt_no_forgetting", "D_power_features(REMEM)"):
        print(nm); print(cal[cal.model == nm].round(3).to_string(index=False))
    t = res[(res.split == "test") & (res.subset == "repeats")].set_index("model")
    log_run("exp3_forgetting", "ednet_v3", int(df.student_id.nunique()), SEED, time.time() - t0,
            {"lambda": best_lam, "beta": D.beta, "features": D.features}, t[["auc", "logloss", "ece"]].round(4).to_dict("index"),
            "experiments/results/exp3_forgetting_metrics.csv")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
