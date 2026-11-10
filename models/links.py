"""Concept-linked failure feature F (spec 9.5, Experiment 9).

  w_{cc'} in [0, 1]   how strongly failing concept c' goes with failing concept c (from TRAIN rows only)
  F_{s,c}(t) = sum_{c'} w_{cc'} * sum over earlier failures of student s on c' of exp(-(t - t_fail) / tau_F)

Everything is strictly causal: F for an interaction uses only that student's EARLIER interactions on OTHER concepts.
The decayed failure sum is kept as a running vector, so no hard window is needed (the exponential decay does the work).
The similarity is a normalised co-error correlation, not a curated prerequisite graph, and the feature is judged only by
whether it improves held-out prediction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MS_PER_DAY = 86_400_000.0


def residual_error_table(train: pd.DataFrame, min_rows: int = 5) -> pd.DataFrame:
    """Students x concepts table of (the student's error rate on the concept - the student's overall error rate).
    A cell is empty (NaN) when the student has fewer than `min_rows` training interactions on the concept."""
    err = 1.0 - train["correct"].astype(float)
    t = pd.DataFrame({"s": train["student_id"].to_numpy(), "c": train["concept_id"].to_numpy(), "e": err.to_numpy()})
    overall = t.groupby("s")["e"].mean()
    g = t.groupby(["s", "c"])["e"].agg(["mean", "size"]).reset_index()
    g = g[g["size"] >= min_rows]
    g["resid"] = g["mean"] - g["s"].map(overall)
    return g.pivot(index="s", columns="c", values="resid")


def similarity_matrix(train: pd.DataFrame, concept_ids, min_students: int = 30, min_rows: int = 5) -> np.ndarray:
    """Pearson correlation of residual error across students for every concept pair; negative or unsupported pairs and the
    diagonal are set to 0. Row/column order follows `concept_ids`."""
    tab = residual_error_table(train, min_rows).reindex(columns=list(concept_ids))
    corr = tab.corr(min_periods=min_students).to_numpy()
    corr = np.nan_to_num(corr, nan=0.0)
    corr = np.clip(corr, 0.0, 1.0)
    np.fill_diagonal(corr, 0.0)
    return corr


def neighbour_weights(corr: np.ndarray, k: int, threshold: float) -> np.ndarray:
    """Keep, for each concept, its top-k neighbours with correlation above `threshold`; scale so the largest weight is 1."""
    W = np.zeros_like(corr)
    for i in range(corr.shape[0]):
        row = corr[i]
        top = np.argsort(-row)[:k]
        top = top[row[top] > threshold]
        W[i, top] = row[top]
    m = W.max()
    return W / m if m > 0 else W


def link_feature(df: pd.DataFrame, W: np.ndarray, concept_ids, tau_days: float) -> np.ndarray:
    """F for every row of `df` (aligned to df's row order). Needs student_id, concept_id, timestamp (ms) and correct."""
    ids = np.asarray(list(concept_ids))
    cidx = np.searchsorted(ids, df["concept_id"].to_numpy())
    known = (cidx < len(ids)) & (ids[np.minimum(cidx, len(ids) - 1)] == df["concept_id"].to_numpy())
    cidx = np.where(known, cidx, 0)
    ts = df["timestamp"].to_numpy(float)
    failed = (df["correct"].to_numpy() == 0)
    stud = pd.factorize(df["student_id"])[0]
    order = np.lexsort((np.arange(len(df)), ts, stud))
    out = np.zeros(len(df))
    n_c = len(ids)
    G = np.zeros(n_c)                                   # decayed failure mass per concept for the current student
    last_t, prev_s = 0.0, -1
    for pos in order:
        s = stud[pos]
        if s != prev_s:
            G[:] = 0.0
            last_t, prev_s = ts[pos], s
        dt = (ts[pos] - last_t) / MS_PER_DAY
        if dt > 0:
            G *= np.exp(-dt / tau_days)
            last_t = ts[pos]
        if known[pos]:
            out[pos] = W[cidx[pos]] @ G                 # strictly earlier failures only: this row's outcome is added AFTER
            if failed[pos]:
                G[cidx[pos]] += 1.0
    return out
