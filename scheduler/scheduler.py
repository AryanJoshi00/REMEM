"""Review scheduler (spec 10): invert the forgetting curve at the target retention theta.

  t_review = (S / k) * (theta^(-1/beta) - 1)      days after the last interaction
  clipped to [t_min, t_max]; items ranked by ascending current retrievability.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from models.stability import k_of_beta, retrievability_power

T_MIN_DAYS = 1.0
T_MAX_DAYS = 180.0
DEFAULT_THETA = 0.85


def t_review_days(S: float, beta: float, theta: float = DEFAULT_THETA, t_min: float = T_MIN_DAYS, t_max: float = T_MAX_DAYS) -> float:
    """Days until predicted recall falls to theta (clipped to the configured bounds)."""
    if not 0 < theta < 1:
        raise ValueError("theta must be in (0, 1)")
    raw = (S / k_of_beta(beta)) * (theta ** (-1.0 / beta) - 1.0)
    return float(np.clip(raw, t_min, t_max))


def current_R(S: float, beta: float, days_since_last: float) -> float:
    return float(retrievability_power(days_since_last, S, beta))


@dataclass
class DueItem:
    concept_id: str
    R_now: float
    S_days: float
    due_in_days: float          # <= 0 means due now
    t_review_days: float


def build_due_list(items: list[dict], beta: float, now_days: float, theta: float = DEFAULT_THETA,
                   t_min: float = T_MIN_DAYS, t_max: float = T_MAX_DAYS) -> list[DueItem]:
    """items: dicts with concept_id, S_days, last_days (timestamp of last interaction in days).

    Returns every item with its status; callers filter on due_in_days <= 0. Sorted by ascending R_now.
    """
    out = []
    for it in items:
        S = it["S_days"]
        t_rev = t_review_days(S, beta, theta, t_min, t_max)
        elapsed = now_days - it["last_days"]
        out.append(DueItem(it["concept_id"], current_R(S, beta, elapsed), S, t_rev - elapsed, t_rev))
    return sorted(out, key=lambda d: d.R_now)
