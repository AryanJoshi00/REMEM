"""Learning engine used by the API: ONE implementation shared with the offline experiments.

Uses models.bkt (mastery), models.stability (S, R) and scheduler.scheduler (t_review).
State after each answer is computed from the POST-update features, exactly as in the fit (spec 10).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from backend import config
from baselines.sm2 import SM2State, fixed_interval, quality_from_response, sm2_update
from models.bkt import BKTParams, update_mastery
from models.stability import StabilityModel, retrievability_power
from scheduler.scheduler import t_review_days

DEFAULT_STABILITY = {"features": ["m", "log_n", "ability", "difficulty", "rt_z"], "w": [1.1, 1.0, 0.3, 0.5, 0.0, 0.0], "beta": 0.5, "curve": "power", "lam": 1e-3}
DEFAULT_BKT = {"L0": 0.3, "T": 0.1, "G": 0.2, "S": 0.1}


@dataclass
class Models:
    stability: StabilityModel
    bkt: BKTParams          # parameters used for brand-new notes concepts

    @staticmethod
    def load(art=config.ARTIFACTS) -> "Models":
        sp = art / "stability_model.json"
        stab = StabilityModel.from_dict(json.loads(sp.read_text()) if sp.exists() else DEFAULT_STABILITY)
        nb = art / "bkt_notes.json"
        if nb.exists():
            d = json.loads(nb.read_text())
        else:
            bp = art / "bkt_params.json"
            d = json.loads(bp.read_text())["pooled"] if bp.exists() else DEFAULT_BKT
        # guess is fixed by design for 4-option MCQs (spec 9.7)
        return Models(stab, BKTParams(L0=d["L0"], T=d["T"], G=config.MCQ_GUESS, S=min(d["S"], 0.3)))


def feature_vector(models: Models, m: float, n_sessions: int, ability: float) -> np.ndarray:
    vals = {"m": m, "log_n": float(np.log1p(n_sessions)), "ability": ability, "difficulty": config.DEFAULT_DIFFICULTY, "rt_z": 0.0}
    return np.array([[vals[f] for f in models.stability.features]])


def stability_days(models: Models, m: float, n_sessions: int, ability: float) -> float:
    return float(models.stability.stability(feature_vector(models, m, n_sessions, ability))[0])


def current_R(models: Models, S_days: float, last_ts: int, now_ts: int) -> float:
    return float(retrievability_power((now_ts - last_ts) / config.MS_PER_DAY, S_days, models.stability.beta))


def plural(n: float, word: str, digits: int = 0) -> str:
    """'1 day', '2 days', '1.5 days' - singular only when the shown number is exactly 1."""
    shown = f"{n:.{digits}f}"
    if "." in shown:
        shown = shown.rstrip("0").rstrip(".")                  # 3.0 -> 3
    return f"{shown} {word}" if float(shown) == 1.0 else f"{shown} {word}s"


def explain(concept_name: str, R_now: float, theta: float, n_sessions: int, days_since: float, S_days: float, short: bool = False) -> str:
    """Grounded explanation: only computed quantities (spec 11.2). `short` is the one-line card version."""
    if days_since < 0.05:
        recent = "You just practised this."
    else:
        recent = f"Last practised {plural(days_since, 'day', 1)} ago."
    if short:
        if R_now < theta:
            return f"Time to review - recall has dropped to about {R_now:.0%}."
        return f"{recent} You should still remember most of it."
    if R_now < theta:
        head = f"Review **{concept_name}** now - estimated recall is {R_now:.0%}, below your {theta:.0%} target."
    else:
        head = f"**{concept_name}** is still fresh - estimated recall is {R_now:.0%} (REMEM reminds you when it falls to {theta:.0%})."
    return (f"{head} You have practised it in {plural(n_sessions, 'session')}. {recent} "
            f"You tend to remember this for about {plural(S_days, 'day')}.")


def apply_response(models: Models, state: dict, user_ability: float, arm: str, correct: bool, rt_ms: int, ts_ms: int,
                   theta: float = config.THETA, t_min: float = config.T_MIN_DAYS, t_max: float = config.T_MAX_DAYS,
                   median_rt_ms: float = 15000.0):
    """Return (new_state, new_ability, info). `state` is a dict of the `state` table (or {} for a first exposure)."""
    first = not state or state.get("last_ts") is None
    m_prev = config_L0(models) if first else state["mastery"]
    pred_R = None if first else current_R(models, state["stability_days"], state["last_ts"], ts_ms)
    elapsed_days = None if first else (ts_ms - state["last_ts"]) / config.MS_PER_DAY
    was_due = None if first else bool(ts_ms >= (state["due_at"] or 0))

    m_new = update_mastery(m_prev, int(correct), models.bkt)
    new_session = first or (ts_ms - state["last_ts"]) > config.SESSION_GAP_MS
    n_sessions = (0 if first else state["n_sessions"]) + (1 if new_session else 0)
    ability = config.ABILITY_GAMMA * user_ability + (1 - config.ABILITY_GAMMA) * (1.0 if correct else 0.0)

    S = stability_days(models, m_new, n_sessions, ability)
    t_rev = t_review_days(S, models.stability.beta, theta, t_min, t_max)
    remem_due = ts_ms + int(t_rev * config.MS_PER_DAY)

    sm = SM2State(state.get("sm2_ef", 2.5) if state else 2.5, state.get("sm2_reps", 0) if state else 0, state.get("sm2_interval", 0.0) if state else 0.0)
    sm = sm2_update(sm, quality_from_response(correct, rt_ms or 0, median_rt_ms))
    if arm == "sm2":
        due = ts_ms + int(sm.interval_days * config.MS_PER_DAY)
    elif arm == "fixed":
        due = ts_ms + int(fixed_interval(config.FIXED_INTERVAL_DAYS) * config.MS_PER_DAY)
    else:
        due = remem_due

    new_state = {"mastery": m_new, "n_sessions": n_sessions, "n_responses": (0 if first else state["n_responses"]) + 1,
                 "last_ts": ts_ms, "stability_days": S, "t_review_days": t_rev, "due_at": due, "remem_due_at": remem_due,
                 "sm2_ef": sm.ef, "sm2_reps": sm.reps, "sm2_interval": sm.interval_days}
    info = {"pred_R": pred_R, "elapsed_days": elapsed_days, "was_due": was_due, "mode": "first" if first else "review"}
    return new_state, ability, info


def config_L0(models: Models) -> float:
    return models.bkt.L0
