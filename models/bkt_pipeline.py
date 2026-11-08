"""Fit BKT per concept on TRAIN rows, then filter every row chronologically (spec 8.1, 8.2).

Output columns added to the frame:
  bkt_prior   mastery BEFORE observing the row's answer (uses earlier rows only)
  bkt_post    mastery AFTER the row's answer and learning transition
  bkt_pcorrect  standard BKT prediction of the row's correctness (no forgetting)
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd

from models.bkt import BKTParams, filter_batch, fit_bkt

MIN_TRAIN_OBS = 200       # concepts below this use pooled parameters
FIT_SEQ_CAP = 40          # only the first 40 train observations of each sequence are used for fitting
MAX_FIT_SEQS = 1500       # subsample sequences per concept for fitting speed


def _train_seqs(sub: pd.DataFrame, rng: np.random.Generator):
    tr = sub[sub["split"] == "train"]
    seqs = [g["correct"].to_numpy()[:FIT_SEQ_CAP] for _, g in tr.groupby("student_id", sort=False)]
    if len(seqs) > MAX_FIT_SEQS:
        idx = rng.choice(len(seqs), MAX_FIT_SEQS, replace=False)
        seqs = [seqs[i] for i in idx]
    return seqs


def fit_all(df: pd.DataFrame, seed: int = 0, verbose: bool = True):
    """Return (params_by_concept, pooled_params). Uses train rows only."""
    rng = np.random.default_rng(seed)
    df = df.sort_values(["concept_id", "student_id", "timestamp"], kind="mergesort")
    tr = df[df["split"] == "train"]
    # pooled parameters from a random sample of train sequences across all concepts
    pooled_seqs = []
    for _, g in tr.groupby(["concept_id", "student_id"], sort=False):
        if len(g) >= 3:
            pooled_seqs.append(g["correct"].to_numpy()[:FIT_SEQ_CAP])
    pooled_seqs = [pooled_seqs[i] for i in rng.choice(len(pooled_seqs), min(4000, len(pooled_seqs)), replace=False)]
    pooled = fit_bkt(pooled_seqs, seed=seed)
    params = {}
    counts = tr.groupby("concept_id").size()
    t0 = time.time()
    for k, (c, sub) in enumerate(df.groupby("concept_id", sort=True)):
        if counts.get(c, 0) < MIN_TRAIN_OBS:
            params[int(c)] = pooled
            continue
        seqs = _train_seqs(sub, rng)
        params[int(c)] = fit_bkt(seqs, n_starts=2, seed=seed, maxiter=40)
        if verbose and (k + 1) % 20 == 0:
            print(f"  fitted {k+1} concepts ({time.time()-t0:.0f}s)")
    return params, pooled


def filter_all(df: pd.DataFrame, params: dict, pooled: BKTParams) -> pd.DataFrame:
    """Run BKT filtering over ALL rows (train+val+test) in time order; attach mastery columns."""
    df = df.sort_values(["concept_id", "student_id", "timestamp"], kind="mergesort").reset_index(drop=True)
    pos = df.groupby(["concept_id", "student_id"]).cumcount().to_numpy()
    prior = np.zeros(len(df))
    post = np.zeros(len(df))
    pc = np.zeros(len(df))
    y_all = df["correct"].to_numpy()
    for c, idx in df.groupby("concept_id").indices.items():
        prm = params.get(int(c), pooled)
        sub_students = df["student_id"].to_numpy()[idx]
        codes, inv = np.unique(sub_students, return_inverse=True)
        T = int(pos[idx].max()) + 1
        Y = np.zeros((len(codes), T), dtype=np.int8)
        M = np.zeros((len(codes), T), dtype=bool)
        Y[inv, pos[idx]] = y_all[idx]
        M[inv, pos[idx]] = True
        pr, po, _ = filter_batch(Y, M, prm)
        p_prior = pr[inv, pos[idx]]
        prior[idx] = p_prior
        post[idx] = po[inv, pos[idx]]
        pc[idx] = p_prior * (1 - prm.S) + (1 - p_prior) * prm.G
    df["bkt_prior"] = prior
    df["bkt_post"] = post
    df["bkt_pcorrect"] = pc
    return df
