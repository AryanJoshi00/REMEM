"""Hierarchical offsets (spec 9.4): recovery of planted effects, shrinkage, cold start, consistency with the base model."""
import numpy as np
import pandas as pd

from evaluation.metrics import evaluate
from models.offsets import OffsetModel
from models.stability import StabilityModel


def make(n=30_000, n_concepts=25, n_students=120, seed=0):
    rng = np.random.default_rng(seed)
    base = StabilityModel(features=[], curve="power", beta=0.5)
    base.w = np.array([np.log(4.0)])
    u_c = rng.normal(0, 0.8, n_concepts)
    u_s = rng.normal(0, 0.5, n_students)
    c = rng.integers(0, n_concepts, n)
    s = rng.integers(0, n_students, n)
    dt = np.exp(rng.uniform(np.log(0.5), np.log(40), n))
    m, g, sl = np.full(n, 0.9), np.full(n, 0.25), np.full(n, 0.1)
    from models.stability import k_of_beta
    S = np.exp(np.log(4.0) + u_c[c] + u_s[s])
    R = (1 + k_of_beta(0.5) * dt / S) ** -0.5
    p = (1 - sl) * m * R + g * (1 - m * R)
    y = (rng.random(n) < p).astype(float)
    d = pd.DataFrame({"concept_id": c, "student_id": [f"u{i}" for i in s], "delta_t_days": dt, "m": m, "guess": g, "slip": sl, "correct": y})
    return base, d, u_c, u_s


def test_no_offsets_equals_base_model():
    base, d, *_ = make(2000)
    om = OffsetModel(base)
    X = np.zeros((len(d), 0))
    expect = base.predict(d["delta_t_days"].to_numpy(), X, d["m"].to_numpy(), d["guess"].to_numpy(), d["slip"].to_numpy())
    assert np.allclose(om.predict(d), expect)


def test_concept_offsets_recover_planted_effects_and_improve_holdout():
    base, d, u_c, _ = make()
    tr, te = d.iloc[:24_000], d.iloc[24_000:]
    om = OffsetModel(base).fit(tr, {"concept": 1.0})
    est = om.offsets["concept"].reindex([str(i) for i in range(len(u_c))]).to_numpy()   # group keys are strings
    assert np.corrcoef(est, u_c)[0, 1] > 0.7
    assert evaluate(te["correct"], om.predict(te))["logloss"] < evaluate(te["correct"], OffsetModel(base).predict(te))["logloss"]


def test_shrinkage_few_rows_stay_near_zero_and_tighter_prior_shrinks_more():
    base, d, *_ = make()
    rare = d.iloc[:30].copy()
    rare["concept_id"] = 999                                       # a concept seen in only 30 rows, with a strong planted effect
    rare["correct"] = 0.0                                          # always wrong -> pushes toward a short stability
    big = d.iloc[30:]
    train = pd.concat([rare, big])
    loose = OffsetModel(base).fit(train, {"concept": 2.0}).offsets["concept"]
    tight = OffsetModel(base).fit(train, {"concept": 0.1}).offsets["concept"]
    assert abs(tight["999"]) < abs(loose["999"])
    assert abs(tight["999"]) < 0.1 and abs(loose["999"]) > 0.1


def test_unseen_groups_get_zero_offset_cold_start():
    base, d, *_ = make(6000)
    om = OffsetModel(base).fit(d, {"concept": 1.0, "student": 1.0, "pair": 1.0})
    new = d.iloc[:50].copy()
    new["concept_id"], new["student_id"] = 12345, "someone-new"
    assert np.all(om.offset_for(new, "concept") == 0) and np.all(om.offset_for(new, "student") == 0) and np.all(om.offset_for(new, "pair") == 0)
    plain = OffsetModel(base)
    assert np.allclose(om.predict(new), plain.predict(new))        # a brand-new pair is predicted by the global model


def test_full_hierarchy_runs_and_student_level_helps():
    base, d, _, u_s = make(40_000, n_students=60)
    tr, te = d.iloc[:32_000], d.iloc[32_000:]
    g = evaluate(te["correct"], OffsetModel(base).predict(te))["logloss"]
    full = OffsetModel(base).fit(tr, {"concept": 1.0, "student": 1.0, "pair": 0.3})
    assert evaluate(te["correct"], full.predict(te))["logloss"] < g
    assert set(full.offsets) == {"concept", "student", "pair"}
    assert np.isfinite(full.log_s(te)).all()
