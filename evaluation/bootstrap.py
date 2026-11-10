"""Student-level (cluster) bootstrap for differences in mean log loss between two models on the same rows.

Rows from one student are correlated, so the resampling unit is the student, not the row. The result is a mean difference
and a 95% interval; a difference whose interval contains 0 is "not demonstrated" (spec 15.4).
"""
from __future__ import annotations

import numpy as np

EPS = 1e-9


def row_loss(y, p) -> np.ndarray:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def cluster_bootstrap_diff(students, loss_a, loss_b, n_boot: int = 500, seed: int = 0) -> dict:
    """Mean of (loss_a - loss_b) over rows (positive = model b is better) with a 95% student-bootstrap interval."""
    codes, inv = np.unique(np.asarray(students), return_inverse=True)
    diff = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    sums = np.bincount(inv, diff, len(codes))
    counts = np.bincount(inv, None, len(codes)).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(codes), (n_boot, len(codes)))
    boots = sums[pick].sum(1) / counts[pick].sum(1)
    return {"mean_diff": float(sums.sum() / counts.sum()), "lo": float(np.percentile(boots, 2.5)), "hi": float(np.percentile(boots, 97.5)), "n_students": int(len(codes))}
