"""SM-2 baseline scheduler (Wozniak, 1987) and the fixed-interval baseline (spec 10).

Datasets have binary correctness, not a 0-5 rating, so quality q is mapped as:
  q = 5 if correct and faster than the question median, 4 if correct and slower, 2 if incorrect.
"""
from __future__ import annotations

from dataclasses import dataclass

EF_MIN = 1.3


def quality_from_response(correct: bool, rt_ms: float, median_rt_ms: float) -> int:
    if not correct:
        return 2
    return 5 if rt_ms <= median_rt_ms else 4


@dataclass
class SM2State:
    ef: float = 2.5
    reps: int = 0
    interval_days: float = 0.0


def sm2_update(state: SM2State, q: int) -> SM2State:
    """Return the new state after one review with quality q (0-5)."""
    ef = max(EF_MIN, state.ef + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)))
    if q < 3:
        reps, interval = 1, 1.0
    else:
        reps = state.reps + 1
        if reps == 1:
            interval = 1.0
        elif reps == 2:
            interval = 6.0
        else:
            interval = float(round(state.interval_days * ef))
    return SM2State(ef=ef, reps=reps, interval_days=interval)


def fixed_interval(days: float = 3.0) -> float:
    return float(days)
