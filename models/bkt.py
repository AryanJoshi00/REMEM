"""In-house Bayesian Knowledge Tracing (spec 8.1).

Parameters per concept: L0 (prior mastery), T (learn), G (guess), S (slip).
Filtering is vectorised over sequences: one loop step per opportunity index.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

ORDER = ("L0", "T", "G", "S")
BOUNDS = {"L0": (0.01, 0.90), "T": (0.001, 0.50), "G": (0.02, 0.35), "S": (0.02, 0.30)}
EPS = 1e-9


@dataclass(frozen=True)
class BKTParams:
    L0: float
    T: float
    G: float
    S: float

    @staticmethod
    def from_array(a) -> "BKTParams":
        return BKTParams(*[float(x) for x in a])


def update_mastery(p: float, correct: int, prm: BKTParams) -> float:
    """One BKT step: posterior given the observation, then the learning transition."""
    if correct:
        post = p * (1 - prm.S) / (p * (1 - prm.S) + (1 - p) * prm.G)
    else:
        post = p * prm.S / (p * prm.S + (1 - p) * (1 - prm.G))
    return post + (1 - post) * prm.T


def p_correct(p: float, prm: BKTParams) -> float:
    return p * (1 - prm.S) + (1 - p) * prm.G


def filter_batch(Y: np.ndarray, mask: np.ndarray, prm: BKTParams):
    """Filter many sequences at once.

    Y, mask: (N, T). Returns prior mastery before each observation, posterior mastery after each
    observation (including the learning transition), and the total log-likelihood.
    """
    N, T = Y.shape
    prior = np.zeros((N, T))
    post = np.zeros((N, T))
    p = np.full(N, prm.L0)
    ll = 0.0
    for t in range(T):
        m = mask[:, t]
        y = Y[:, t]
        pc = p * (1 - prm.S) + (1 - p) * prm.G
        prior[:, t] = p
        ll += float(np.sum(np.where(m, np.where(y == 1, np.log(pc + EPS), np.log(1 - pc + EPS)), 0.0)))
        num = np.where(y == 1, p * (1 - prm.S), p * prm.S)
        den = np.where(y == 1, pc, 1 - pc)
        posterior = num / np.maximum(den, EPS)
        p = np.where(m, posterior + (1 - posterior) * prm.T, p)
        post[:, t] = p
    return prior, post, ll


def pad_sequences(seqs):
    T = max(len(s) for s in seqs)
    Y = np.zeros((len(seqs), T), dtype=np.int8)
    M = np.zeros((len(seqs), T), dtype=bool)
    for i, s in enumerate(seqs):
        Y[i, :len(s)] = s
        M[i, :len(s)] = True
    return Y, M


def fit_bkt(seqs, n_starts: int = 3, seed: int = 0, maxiter: int = 60) -> BKTParams:
    """Bounded maximum-likelihood fit (multi-start L-BFGS-B) on training sequences."""
    Y, M = pad_sequences(seqs)
    lo = np.array([BOUNDS[k][0] for k in ORDER])
    hi = np.array([BOUNDS[k][1] for k in ORDER])
    rng = np.random.default_rng(seed)

    def nll(a):
        return -filter_batch(Y, M, BKTParams.from_array(a))[2]

    starts = [np.array([0.3, 0.1, 0.2, 0.1])] + [lo + rng.random(4) * (hi - lo) for _ in range(n_starts - 1)]
    best = None
    for x0 in starts:
        r = minimize(nll, x0, method="L-BFGS-B", bounds=list(zip(lo, hi)), options={"maxiter": maxiter})
        if best is None or r.fun < best.fun:
            best = r
    return BKTParams.from_array(best.x)
