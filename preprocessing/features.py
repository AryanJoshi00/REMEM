"""Chronological split and strictly causal feature engineering (spec 7, 9.3, 12.3, 13).

Rule: every feature for row i uses rows < i only. Statistics (difficulty, response-time
median/IQR, ability prior) come from TRAIN rows only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

MS_PER_DAY = 86_400_000.0
SESSION_GAP_DAYS = 30.0 / 1440.0   # a new session starts after a 30-minute gap
ABILITY_GAMMA = 0.9                # EWMA decay for student ability
ABILITY_MIN_HISTORY = 5            # use the global mean until this many prior interactions


@dataclass
class TrainStats:
    cutoff_train: float
    cutoff_val: float
    global_acc: float
    concept_difficulty: dict = field(default_factory=dict)   # D_c = 1 - correct rate
    global_difficulty: float = 0.0
    q_median_rt: dict = field(default_factory=dict)
    q_iqr_rt: dict = field(default_factory=dict)
    global_median_rt: float = 0.0
    global_iqr_rt: float = 1.0


def chronological_split(df: pd.DataFrame, frac_train: float = 0.70, frac_val: float = 0.15):
    """Global time cutoffs: first 70% of time-ordered rows = train, next 15% = val, rest = test."""
    ts = np.sort(df["timestamp"].to_numpy())
    c_train = float(ts[int(len(ts) * frac_train) - 1])
    c_val = float(ts[int(len(ts) * (frac_train + frac_val)) - 1])
    split = np.where(df["timestamp"] <= c_train, "train", np.where(df["timestamp"] <= c_val, "val", "test"))
    out = df.copy()
    out["split"] = split
    return out, c_train, c_val


def fit_train_stats(df: pd.DataFrame, c_train: float, c_val: float) -> TrainStats:
    tr = df[df["timestamp"] <= c_train]
    st = TrainStats(cutoff_train=c_train, cutoff_val=c_val, global_acc=float(tr["correct"].mean()))
    cr = tr.groupby("concept_id")["correct"].agg(["mean", "size"])
    st.concept_difficulty = {int(c): float(1 - r["mean"]) for c, r in cr.iterrows() if r["size"] >= 30}
    st.global_difficulty = 1.0 - st.global_acc
    st.global_median_rt = float(tr["response_time_ms"].median())
    q75, q25 = tr["response_time_ms"].quantile([0.75, 0.25])
    st.global_iqr_rt = float(max(q75 - q25, 1.0))
    g = tr.groupby("question_id")["response_time_ms"]
    med, iqr, cnt = g.median(), g.quantile(0.75) - g.quantile(0.25), g.size()
    ok = cnt[cnt >= 20].index
    st.q_median_rt = med.loc[ok].to_dict()
    st.q_iqr_rt = iqr.loc[ok].clip(lower=1.0).to_dict()
    return st


def add_causal_features(df: pd.DataFrame, st: TrainStats) -> pd.DataFrame:
    """Add ability, delta_t_days, n_sessions, rt_z, concept_difficulty (all causal)."""
    df = df.sort_values(["student_id", "timestamp"], kind="mergesort").reset_index(drop=True)

    # student ability: EWMA of PAST correctness (shift(1) excludes the row's own label)
    prior_n = df.groupby("student_id").cumcount()
    ewma = df.groupby("student_id")["correct"].transform(
        lambda s: s.shift(1).ewm(alpha=1 - ABILITY_GAMMA, adjust=False).mean())
    df["ability"] = np.where(prior_n >= ABILITY_MIN_HISTORY, ewma, st.global_acc)
    df["ability"] = df["ability"].fillna(st.global_acc)

    # per (student, concept) sequence features
    df = df.sort_values(["student_id", "concept_id", "timestamp"], kind="mergesort").reset_index(drop=True)
    grp = ["student_id", "concept_id"]
    gap = df.groupby(grp)["timestamp"].diff() / MS_PER_DAY
    df["delta_t_days"] = gap                                    # NaN on first exposure
    new_sess = gap.isna() | (gap > SESSION_GAP_DAYS)
    sess_idx = new_sess.astype(int).groupby([df["student_id"], df["concept_id"]]).cumsum()
    df["n_sessions"] = sess_idx.groupby([df["student_id"], df["concept_id"]]).shift(1).fillna(0)

    med = df["question_id"].map(st.q_median_rt).fillna(st.global_median_rt)
    iqr = df["question_id"].map(st.q_iqr_rt).fillna(st.global_iqr_rt)
    z = ((df["response_time_ms"] - med) / iqr).clip(-3, 3)
    df["rt_z"] = z.groupby([df["student_id"], df["concept_id"]]).shift(1).fillna(0.0)

    df["concept_difficulty"] = df["concept_id"].map(st.concept_difficulty).fillna(st.global_difficulty)
    df["label_correct"] = df["correct"]
    return df.sort_values(["student_id", "timestamp"], kind="mergesort").reset_index(drop=True)
