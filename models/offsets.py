"""Hierarchical offsets on log stability, fitted by backfitting (spec 9.4, Experiment 4).

    log S_{s,c} = base(features) + u_c + u_s + u_sc          u_level ~ N(0, tau_level^2)

`base` is an already-fitted StabilityModel (global w, beta). Each level's offsets are estimated with the
others held fixed, in the order concept -> student -> pair, using a penalised one-dimensional Newton step per
group (vectorised with bincount). A group with few rows keeps an offset near zero (the prior dominates); a group
with many rows lets the data speak. A group that was never seen in training has offset 0, so cold start needs no
special code. The model is evaluated offline only; the app does not use it (spec decision D15).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from models.stability import LOG_S_MAX, LOG_S_MIN, StabilityModel, k_of_beta

EPS = 1e-9
LEVELS = ("concept", "student", "pair")
H_FD = 0.05                      # step for the finite-difference derivatives of the row log-likelihood (in log S)
MAX_STEP = 1.0                   # largest change of an offset in one Newton step (keeps a flat likelihood from jumping)


def _keys(d: pd.DataFrame, level: str) -> pd.Series:
    if level == "concept":
        return d["concept_id"].astype(str)
    if level == "student":
        return d["student_id"].astype(str)
    return d["student_id"].astype(str) + "|" + d["concept_id"].astype(str)


def base_log_s(base: StabilityModel, d: pd.DataFrame) -> np.ndarray:
    """Unclipped log S from the global model's features (clipping happens once, after the offsets are added)."""
    X = d[base.features].to_numpy(float) if base.features else np.zeros((len(d), 0))
    return base.w[0] + X @ base.w[1:]


def _row_nll(z, dt, k, beta, m, g, s, y):
    S = np.exp(np.clip(z, LOG_S_MIN, LOG_S_MAX))
    R = np.exp(-beta * np.log1p(k * dt / S))
    m_eff = m * R
    p = np.clip((1 - s) * m_eff + g * (1 - m_eff), EPS, 1 - EPS)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


@dataclass
class OffsetModel:
    base: StabilityModel
    taus: dict = field(default_factory=dict)            # level -> prior sd
    offsets: dict = field(default_factory=dict)         # level -> pd.Series(index = group key, value = offset)

    # ------------------------------------------------------------------ fitting
    def fit(self, d: pd.DataFrame, taus: dict, iters: int = 3, passes: int = 1) -> "OffsetModel":
        """d must hold: delta_t_days, m, guess, slip, correct, concept_id, student_id and the base model's feature columns."""
        self.taus = dict(taus)
        dt = d["delta_t_days"].to_numpy(float)
        m, g, s, y = (d[c].to_numpy(float) for c in ("m", "guess", "slip", "correct"))
        beta = float(self.base.beta)
        k = k_of_beta(beta)
        z0 = base_log_s(self.base, d)
        codes, uniques = {}, {}
        for lv in LEVELS:
            if lv in self.taus:
                codes[lv], uniques[lv] = pd.factorize(_keys(d, lv))
        u = {lv: np.zeros(len(uniques[lv])) for lv in codes}
        for _ in range(passes):
            for lv in LEVELS:
                if lv not in codes:
                    continue
                others = sum(u[o][codes[o]] for o in codes if o != lv) if len(codes) > 1 else 0.0
                tau2 = float(self.taus[lv]) ** 2
                n_groups = len(uniques[lv])
                for _ in range(iters):
                    z = z0 + others + u[lv][codes[lv]]
                    f0, fp, fm = (_row_nll(z + dz, dt, k, beta, m, g, s, y) for dz in (0.0, H_FD, -H_FD))
                    grad = np.bincount(codes[lv], (fp - fm) / (2 * H_FD), n_groups)
                    hess = np.bincount(codes[lv], (fp - 2 * f0 + fm) / H_FD ** 2, n_groups)
                    step = (grad + u[lv] / tau2) / (np.maximum(hess, 0.0) + 1.0 / tau2)
                    u[lv] = u[lv] - np.clip(step, -MAX_STEP, MAX_STEP)
        self.offsets = {lv: pd.Series(u[lv], index=uniques[lv]) for lv in u}
        return self

    # ------------------------------------------------------------------ prediction
    def offset_for(self, d: pd.DataFrame, level: str) -> np.ndarray:
        if level not in self.offsets:
            return np.zeros(len(d))
        return self.offsets[level].reindex(_keys(d, level)).fillna(0.0).to_numpy()      # unseen group -> 0 (cold start)

    def log_s(self, d: pd.DataFrame) -> np.ndarray:
        z = base_log_s(self.base, d)
        for lv in self.offsets:
            z = z + self.offset_for(d, lv)
        return np.clip(z, LOG_S_MIN, LOG_S_MAX)

    def predict(self, d: pd.DataFrame) -> np.ndarray:
        dt = d["delta_t_days"].to_numpy(float)
        k, beta = k_of_beta(self.base.beta), float(self.base.beta)
        R = np.exp(-beta * np.log1p(k * dt / np.exp(self.log_s(d))))
        m_eff = d["m"].to_numpy(float) * R
        s, g = d["slip"].to_numpy(float), d["guess"].to_numpy(float)
        return (1 - s) * m_eff + g * (1 - m_eff)
