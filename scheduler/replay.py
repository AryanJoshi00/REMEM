"""Offline replay checks for the scheduler (spec 15.1 Experiment 6).

These are descriptive checks on logged answers, not a test of whether following the schedule helps learning:
every number here is judged by REMEM's own model, so it is circular as evidence of benefit (spec 18). What the
replay can honestly show is (a) whether the predicted probability of a correct answer is calibrated for reviews that
happened near the time REMEM would have recommended, and (b) how the recommended gap and review load change with θ.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from models.stability import StabilityModel, k_of_beta
from scheduler.scheduler import DEFAULT_THETA, T_MAX_DAYS, T_MIN_DAYS

THETAS = (0.75, 0.80, 0.85, 0.90, 0.95)
RATIO_EDGES = [0.0, 0.25, 0.5, 0.8, 1.25, 2.0, 4.0, np.inf]
RATIO_LABELS = ["under 0.25x", "0.25-0.5x", "0.5-0.8x", "on time (0.8-1.25x)", "1.25-2x", "2-4x", "over 4x"]
ON_TIME = (0.8, 1.25)
SUPPORT = (0.75, 1 / 0.75)                       # an observed gap counts as "near" a recommendation within this ratio band
MONTH_DAYS = 30.0


def recommended_gap_days(S, beta: float, theta: float = DEFAULT_THETA, t_min: float = T_MIN_DAYS, t_max: float = T_MAX_DAYS):
    """Vectorised form of scheduler.scheduler.t_review_days: days until predicted recall falls to θ, clipped to the safety rails."""
    if not 0 < theta < 1:
        raise ValueError("theta must be in (0, 1)")
    raw = (np.asarray(S, float) / k_of_beta(beta)) * (theta ** (-1.0 / beta) - 1.0)
    return np.clip(raw, t_min, t_max)


def stability_for(model: StabilityModel, d: pd.DataFrame) -> np.ndarray:
    X = d[model.features].to_numpy(float) if model.features else np.zeros((len(d), 0))
    return model.stability(X)


def predicted_p(model: StabilityModel, d: pd.DataFrame) -> np.ndarray:
    X = d[model.features].to_numpy(float) if model.features else np.zeros((len(d), 0))
    return model.predict(d["delta_t_days"].to_numpy(float), X, d["m"].to_numpy(float), d["guess"].to_numpy(float), d["slip"].to_numpy(float))


def timing_calibration(actual_gap, rec_gap, p, y) -> pd.DataFrame:
    """Predicted vs observed correctness, grouped by how the actual gap compares with the recommended gap."""
    ratio = np.asarray(actual_gap, float) / np.asarray(rec_gap, float)
    bucket = pd.cut(ratio, RATIO_EDGES, labels=RATIO_LABELS, include_lowest=True, right=False)
    t = pd.DataFrame({"bucket": bucket, "p": np.asarray(p, float), "y": np.asarray(y, float)})
    g = t.groupby("bucket", observed=False)
    out = pd.DataFrame({"n": g.size(), "predicted": g["p"].mean(), "observed": g["y"].mean()}).reset_index()
    out["share"] = out["n"] / max(int(out["n"].sum()), 1)
    out["abs_gap"] = (out["observed"] - out["predicted"]).abs()
    out["bucket"] = out["bucket"].astype(str)
    return out


def theta_sweep(model: StabilityModel, d: pd.DataFrame, thetas=THETAS, t_min: float = T_MIN_DAYS, t_max: float = T_MAX_DAYS) -> pd.DataFrame:
    """For each θ: the recommended gaps for every logged review, the implied review load, and how many real reviews
    happened near the recommendation (with their predicted and observed correctness)."""
    S = stability_for(model, d)
    actual = d["delta_t_days"].to_numpy(float)
    p = predicted_p(model, d)
    y = d["correct"].to_numpy(float)
    rows = []
    for th in thetas:
        rec = recommended_gap_days(S, model.beta, th, t_min, t_max)
        near = (actual / rec >= SUPPORT[0]) & (actual / rec <= SUPPORT[1])
        rows.append({
            "theta": th, "mean_recommended_days": float(rec.mean()), "median_recommended_days": float(np.median(rec)),
            "share_at_max_rail": float((rec >= t_max - 1e-9).mean()), "share_at_min_rail": float((rec <= t_min + 1e-9).mean()),
            "reviews_per_concept_month": float((MONTH_DAYS / rec).mean()),
            "n_near_recommendation": int(near.sum()),
            "predicted_near": float(p[near].mean()) if near.any() else np.nan,
            "observed_near": float(y[near].mean()) if near.any() else np.nan,
        })
    return pd.DataFrame(rows)
