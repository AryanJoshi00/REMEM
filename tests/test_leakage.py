"""Leakage tests (spec 13): split cutoffs, feature causality, train-only statistics."""
import numpy as np
import pandas as pd

from preprocessing.features import add_causal_features, chronological_split, fit_train_stats

DAY = 86_400_000


def make_df(seed=0, n_students=6, n_rows=60):
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_students):
        ts = np.sort(rng.integers(0, 40 * DAY, n_rows))
        for t in ts:
            q = int(rng.integers(0, 12))
            rows.append({"student_id": f"u{s}", "question_id": f"q{q}", "concept_id": q % 4, "part": 5,
                         "timestamp": int(t), "correct": int(rng.random() < 0.6), "response_time_ms": int(rng.integers(5000, 60000))})
    return pd.DataFrame(rows)


def prepared(df):
    d, ct, cv = chronological_split(df)
    st = fit_train_stats(d, ct, cv)
    return d, st, ct, cv


def test_split_is_chronological_and_disjoint():
    d, st, ct, cv = prepared(make_df())
    assert d.loc[d.split == "train", "timestamp"].max() <= ct
    assert d.loc[d.split == "val", "timestamp"].min() > ct and d.loc[d.split == "val", "timestamp"].max() <= cv
    assert d.loc[d.split == "test", "timestamp"].min() > cv
    assert set(d.split.unique()) == {"train", "val", "test"}


def test_features_do_not_use_own_or_future_label():
    d, st, *_ = prepared(make_df())
    base = add_causal_features(d, st)
    # flip the label of one row and rebuild features with the SAME train statistics
    d2 = d.copy()
    idx = d2.index[(d2.student_id == "u2")][30]
    key = (d2.loc[idx, "student_id"], d2.loc[idx, "timestamp"], d2.loc[idx, "question_id"])
    d2.loc[idx, "correct"] = 1 - d2.loc[idx, "correct"]
    pert = add_causal_features(d2, st)
    m = lambda f: f[(f.student_id == key[0]) & (f.timestamp == key[1]) & (f.question_id == key[2])].index[0]
    i0, i1 = m(base), m(pert)
    feats = ["ability", "delta_t_days", "n_sessions", "rt_z", "concept_difficulty"]
    # same row: features identical (own label excluded)
    for f in feats:
        assert (base.loc[i0, f] == pert.loc[i1, f]) or (np.isnan(base.loc[i0, f]) and np.isnan(pert.loc[i1, f]))
    # earlier rows of that student: ability identical
    a = base[(base.student_id == key[0]) & (base.timestamp < key[1])]["ability"].to_numpy()
    b = pert[(pert.student_id == key[0]) & (pert.timestamp < key[1])]["ability"].to_numpy()
    assert np.array_equal(a, b)
    # a later row of that student SHOULD change (the flipped label is now in its past)
    la = base[(base.student_id == key[0]) & (base.timestamp > key[1])]["ability"].to_numpy()
    lb = pert[(pert.student_id == key[0]) & (pert.timestamp > key[1])]["ability"].to_numpy()
    assert not np.array_equal(la, lb)


def test_train_statistics_ignore_val_and_test_rows():
    d, st, ct, cv = prepared(make_df())
    d2 = d.copy()
    later = d2["timestamp"] > ct
    d2.loc[later, "correct"] = 1 - d2.loc[later, "correct"]
    d2.loc[later, "response_time_ms"] = d2.loc[later, "response_time_ms"] * 7
    st2 = fit_train_stats(d2, ct, cv)
    assert st.concept_difficulty == st2.concept_difficulty
    assert st.global_acc == st2.global_acc and st.global_median_rt == st2.global_median_rt


def test_first_exposure_has_no_gap_and_sessions_start_at_zero():
    d, st, *_ = prepared(make_df())
    f = add_causal_features(d, st)
    first = f.groupby(["student_id", "concept_id"]).head(1)
    assert first["delta_t_days"].isna().all() and (first["n_sessions"] == 0).all()
    assert (f["n_sessions"] >= 0).all()
