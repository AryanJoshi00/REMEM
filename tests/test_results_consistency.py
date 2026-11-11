"""Cross-checks between the logged experiment results: the same model on the same rows must give the same number everywhere.

These read the committed result files, so they also guard against editing one experiment and forgetting to rerun another."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RES = Path(__file__).resolve().parents[1] / "experiments" / "results"
ART = Path(__file__).resolve().parents[1] / "artifacts"


def csv(name):
    p = RES / name
    if not p.exists():
        pytest.skip(f"{name} not present")
    return pd.read_csv(p)


def exp3(model, split="test", subset="repeats"):
    m = csv("exp3_forgetting_metrics.csv")
    return m[(m["split"] == split) & (m["subset"] == subset) & (m["model"] == model)].iloc[0]


def test_full_model_has_one_log_loss_across_experiments():
    d = exp3("D_power_features(REMEM)")
    g = csv("exp4_overall.csv")
    g = g[(g["split"] == "test") & (g["subset"] == "repeats") & (g["model"] == "G")].iloc[0]
    a = csv("exp7_ablations.csv").set_index("model").loc["D"]
    s6 = json.loads((RES / "exp6_summary.json").read_text())["fitted"]
    for other in (g["logloss"], a["logloss"], s6["overall_logloss"]):
        assert abs(other - d["logloss"]) < 1e-9
    assert int(g["n"]) == int(d["n"]) == int(a["n"])                           # the same test rows everywhere


def test_validation_baseline_in_exp9_matches_exp3():
    grid = csv("exp9_grid.csv")
    assert abs(grid["base_val_logloss"].iloc[0] - exp3("D_power_features(REMEM)", split="val")["logloss"]) < 1e-9


def test_extension_rows_in_exp7_match_the_experiments_that_produced_them():
    a = csv("exp7_ablations.csv").set_index("model")
    off = csv("exp4_overall.csv")
    off = off[(off["split"] == "test") & (off["subset"] == "repeats") & (off["model"] == "full")].iloc[0]
    assert abs(a.loc["D+offsets", "logloss"] - off["logloss"]) < 1e-9
    o9 = csv("exp9_overall.csv")
    w = o9[(o9["subset"] == "repeats") & (o9["model"] == "with F")].iloc[0]
    assert abs(a.loc["D+F", "logloss"] - w["logloss"]) < 1e-9
    # the ablation baselines are the same fits as Experiment 3
    for k, name in (("A", "A_bkt_no_forgetting"), ("B", "B_exp_global"), ("C", "C_power_global"), ("E", "E_exp_features")):
        assert abs(a.loc[k, "logloss"] - exp3(name)["logloss"]) < 1e-9


def test_replay_uses_the_deployed_prior_and_the_saved_fit():
    s6 = json.loads((RES / "exp6_summary.json").read_text())
    assert abs(s6["prior"]["beta"] - json.loads((ART / "stability_model.json").read_text())["beta"]) < 1e-12
    assert abs(s6["fitted"]["beta"] - json.loads((ART / "stability_model_ednet.json").read_text())["beta"]) < 1e-12


def test_simlab_operating_point_matches_between_its_two_tables():
    fr, md = csv("exp10_frontier.csv"), csv("exp10_matched.csv")
    for (gen, phi, seed), grp in md.groupby(["gen", "phi", "seed"]):
        ref = fr[(fr["gen"] == gen) & (fr["phi"] == phi) & (fr["seed"] == seed) & (fr["policy"] == "remem") & (np.isclose(fr["knob"], 0.85))]
        assert len(ref) == 1
        assert np.allclose(grp["remem_reviews"], ref["reviews_per_concept"].iloc[0])


def test_ablation_verdicts_follow_their_intervals():
    for _, r in csv("exp7_ablations.csv").iterrows():
        if r["model"] == "D":
            continue
        if r["ci_low"] > 0:
            assert r["verdict"] == "worse than the full model"
        elif r["ci_high"] < 0:
            assert r["verdict"] == "better than the full model"
        else:
            assert r["verdict"] == "no demonstrable difference"
        assert r["ci_low"] <= r["delta_logloss"] <= r["ci_high"]


def test_exp9_verdict_follows_its_rule():
    s = json.loads((RES / "exp9_summary.json").read_text())
    ctrl = csv("exp9_controls.csv")
    specific = bool((ctrl["better_lo"] > 0).all())
    assert s["specific_to_related_concepts"] == specific
    if s["logloss_gain_overall"]["lo"] <= 0:
        assert s["verdict"].startswith("not demonstrated")
    else:
        assert s["verdict"].startswith("supported")
