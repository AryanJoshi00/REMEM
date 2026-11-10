"""Experiment 4 - personalisation by hierarchical offsets (spec 9.4, 15.1, H2 / RQ3).

Question: do shrunken offsets on log stability (concept, then student, then student-concept pair) improve calibration
over the global model, and do they help sparse pairs relative to fitting each pair without shrinkage?

Models, all on top of the fitted global model (artifacts/stability_model_ednet.json):
  G        global model only
  G+c      + concept offsets
  G+c+s    + student offsets
  full     + pair offsets (shrunk)
  full_raw + pair offsets with a very wide prior (effectively unshrunk fitting of each pair)
The prior widths tau are chosen level by level on the validation split. Evaluation is on held-out REPEAT rows of the
test split, overall and stratified by how many training repeats the pair had.
Run from the repo root:  python -m experiments.exp4_personalisation
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
from models.offsets import LEVELS, OffsetModel, _keys
from models.stability import StabilityModel

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "experiments" / "results"
ART = ROOT / "artifacts"
TAU_GRID = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
RAW_PAIR_TAU = 50.0
STRATA = [(0, 0, "0 (new pair)"), (1, 2, "1-2"), (3, 5, "3-5"), (6, 10, "6-10"), (11, 30, "11-30"), (31, 10 ** 9, "31+")]


def stratum(n: float) -> str:
    for lo, hi, name in STRATA:
        if lo <= n <= hi:
            return name
    return STRATA[-1][2]


def main() -> None:
    t0 = time.time()
    df = prep(pd.read_parquet(FEATS))
    rep = df[df["delta_t_days"].notna()]
    tr, va, te = (rep[rep["split"] == s].reset_index(drop=True) for s in ("train", "val", "test"))
    base = StabilityModel.from_dict(json.loads((ART / "stability_model_ednet.json").read_text()))
    print(f"repeat rows: train {len(tr):,} val {len(va):,} test {len(te):,}; base beta {base.beta:.3f}", flush=True)

    # ---- choose tau level by level on validation log loss
    base_ll = evaluate(va["correct"], OffsetModel(base).predict(va))["logloss"]
    chosen: dict[str, float] = {}
    tau_rows = [{"level": "none", "tau": np.nan, "val_logloss": base_ll}]
    for lv in LEVELS:
        best = None
        for tau in TAU_GRID:
            om = OffsetModel(base).fit(tr, {**chosen, lv: tau})
            ll = evaluate(va["correct"], om.predict(va))["logloss"]
            tau_rows.append({"level": lv, "tau": tau, "val_logloss": ll})
            print(f"  {lv:8s} tau={tau:<5} val logloss {ll:.5f} ({time.time()-t0:.0f}s)", flush=True)
            if best is None or ll < best[1]:
                best = (tau, ll)
        chosen[lv] = best[0]                                       # the best width at this level is kept even if it gains little (reported as is)
        print(f"  -> {lv}: tau = {chosen[lv]}", flush=True)

    fits = {"G": OffsetModel(base)}
    sched = [("G+c", {"concept": chosen["concept"]}), ("G+c+s", {k: chosen[k] for k in ("concept", "student")}), ("full", dict(chosen)),
             ("full_raw", {"concept": chosen["concept"], "student": chosen["student"], "pair": RAW_PAIR_TAU})]
    for name, taus in sched:
        fits[name] = OffsetModel(base).fit(tr, taus)
    print(f"final fits done ({time.time()-t0:.0f}s)", flush=True)

    # ---- evaluation
    pair_n = _keys(tr, "pair").value_counts()
    te = te.assign(pair_train_n=pair_n.reindex(_keys(te, "pair")).fillna(0).to_numpy())
    te["stratum"] = te["pair_train_n"].map(stratum)
    rows, strat_rows = [], []
    for split, d in (("val", va), ("test", te)):
        for subset, dd in (("repeats", d), ("spaced>=1d", d[d["delta_t_days"] >= 1.0])):
            for name, om in fits.items():
                rows.append({"split": split, "subset": subset, "model": name, **evaluate(dd["correct"], om.predict(dd))})
    for _, _, label in STRATA:
        dd = te[te["stratum"] == label]
        if len(dd) < 200:
            continue
        for name, om in fits.items():
            strat_rows.append({"stratum": label, "model": name, **evaluate(dd["correct"], om.predict(dd))})
    overall, strat = pd.DataFrame(rows), pd.DataFrame(strat_rows)
    overall.to_csv(RES / "exp4_overall.csv", index=False)
    strat.to_csv(RES / "exp4_by_sparsity.csv", index=False)
    pd.DataFrame(tau_rows).to_csv(RES / "exp4_tau_search.csv", index=False)
    summary = []
    for lv, ser in fits["full"].offsets.items():
        summary.append({"level": lv, "groups": int(len(ser)), "tau": chosen[lv], "offset_sd": float(ser.std()), "share_abs_gt_0.1": float((ser.abs() > 0.1).mean())})
    pd.DataFrame(summary).to_csv(RES / "exp4_offset_summary.csv", index=False)

    pd.set_option("display.width", 200)
    t = overall[(overall.split == "test") & (overall.subset == "repeats")].set_index("model")[["logloss", "auc", "brier", "ece"]]
    print("\nTEST repeat rows:\n", t.round(5).to_string())
    print("\nTEST by pair sparsity (logloss):\n", strat.pivot_table(index="stratum", columns="model", values="logloss").reindex([s[2] for s in STRATA]).round(5).to_string())
    print("\nOffset summary:\n", pd.DataFrame(summary).round(3).to_string(index=False))
    log_run("exp4_personalisation", "ednet_v3", int(df.student_id.nunique()), 0, time.time() - t0,
            {"tau": chosen, "raw_pair_tau": RAW_PAIR_TAU, "tau_grid": list(TAU_GRID), "base_beta": float(base.beta)},
            t.round(5).to_dict("index"), "experiments/results/exp4_overall.csv")
    print(f"total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
