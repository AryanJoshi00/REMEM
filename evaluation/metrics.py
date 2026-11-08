"""Prediction metrics (spec 15.3): AUC, log loss, Brier, accuracy, RMSE, ECE + reliability bins."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

EPS = 1e-9


def reliability_table(y, p, n_bins: int = 10) -> pd.DataFrame:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), 0, 1)
    bins = np.minimum((p * n_bins).astype(int), n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = bins == b
        if m.any():
            rows.append({"bin": b, "n": int(m.sum()), "mean_pred": p[m].mean(), "obs_rate": y[m].mean()})
    return pd.DataFrame(rows)


def ece(y, p, n_bins: int = 10) -> float:
    t = reliability_table(y, p, n_bins)
    return float((t["n"] * (t["mean_pred"] - t["obs_rate"]).abs()).sum() / t["n"].sum())


def evaluate(y, p) -> dict:
    y = np.asarray(y, float)
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return {
        "n": int(len(y)),
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan"),
        "logloss": float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))),
        "brier": float(np.mean((p - y) ** 2)),
        "accuracy": float(np.mean((p >= 0.5) == (y == 1))),
        "rmse": float(np.sqrt(np.mean((p - y) ** 2))),
        "ece": ece(y, p),
    }
