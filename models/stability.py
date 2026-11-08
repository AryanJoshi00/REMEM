"""Memory stability + forgetting model (spec 8.3, 9).

  R(dt)   = (1 + k*dt/S)^(-beta),  k = 0.9^(-1/beta) - 1      (power law, R(S) = 0.9)
  R_exp   = 0.9^(dt/S)                                          (exponential, R(S) = 0.9)
  log S   = w . x            x = [1, m, log(1+n), ability, difficulty, rt_z (, link_F)]
  m_eff   = m * R
  p_hat   = (1 - slip) * m_eff + guess * (1 - m_eff)

S is never observed: w and beta are fitted by maximising the likelihood of the observed next
answers (ridge penalty on w except the intercept).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

EPS = 1e-9
LOG_S_MIN, LOG_S_MAX = np.log(0.05), np.log(3650.0)
BETA_MIN, BETA_MAX = 0.01, 3.0
ALL_FEATURES = ["m", "log_n", "ability", "difficulty", "rt_z"]   # intercept is implicit


def k_of_beta(beta: float) -> float:
    return 0.9 ** (-1.0 / beta) - 1.0


def retrievability_power(dt, S, beta):
    return np.exp(-beta * np.log1p(k_of_beta(beta) * np.asarray(dt, float) / S))


def retrievability_exp(dt, S):
    return 0.9 ** (np.asarray(dt, float) / S)


def predict_p(m, R, guess, slip):
    m_eff = np.asarray(m, float) * R
    return (1 - slip) * m_eff + guess * (1 - m_eff)


@dataclass
class StabilityModel:
    features: list = field(default_factory=lambda: list(ALL_FEATURES))
    w: np.ndarray = None            # length 1 + len(features): intercept first
    beta: float = 0.5
    curve: str = "power"            # "power" or "exp"
    lam: float = 1e-3

    def log_S(self, X: np.ndarray) -> np.ndarray:
        return np.clip(self.w[0] + X @ self.w[1:], LOG_S_MIN, LOG_S_MAX)

    def stability(self, X: np.ndarray) -> np.ndarray:
        return np.exp(self.log_S(X))

    def retrievability(self, dt, X):
        S = self.stability(X)
        return retrievability_power(dt, S, self.beta) if self.curve == "power" else retrievability_exp(dt, S)

    def predict(self, dt, X, m, guess, slip):
        return predict_p(m, self.retrievability(dt, X), guess, slip)

    # ------------------------------------------------------------------ fitting
    def fit(self, dt, X, m, guess, slip, y, maxiter: int = 80):
        """Regularised maximum-likelihood fit. X has shape (N, len(features)); pass zeros-width X for global-S."""
        dt = np.asarray(dt, float); y = np.asarray(y, float)
        d = X.shape[1]
        n = len(y)
        w_init = np.zeros(1 + d); w_init[0] = np.log(3.0)
        x0 = np.concatenate([w_init, [self.beta]])
        bounds = [(-5, 10)] + [(-6, 6)] * d + [(BETA_MIN, BETA_MAX)]
        if self.curve == "exp":
            x0 = x0[:-1]; bounds = bounds[:-1]

        def unpack(a):
            return a[:1 + d], (a[-1] if self.curve == "power" else None)

        def loss(a):
            w, beta = unpack(a)
            logS = np.clip(w[0] + X @ w[1:], LOG_S_MIN, LOG_S_MAX) if d else np.full(n, np.clip(w[0], LOG_S_MIN, LOG_S_MAX))
            S = np.exp(logS)
            R = retrievability_power(dt, S, beta) if self.curve == "power" else retrievability_exp(dt, S)
            p = np.clip(predict_p(m, R, guess, slip), EPS, 1 - EPS)
            nll = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
            return nll + self.lam * float(np.sum(w[1:] ** 2))

        r = minimize(loss, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": maxiter})
        w, beta = unpack(r.x)
        self.w = np.array(w)
        if beta is not None:
            self.beta = float(beta)
        self.train_loss = float(r.fun)
        return self

    # ------------------------------------------------------------------ io
    def to_dict(self) -> dict:
        return {"features": self.features, "w": [float(v) for v in self.w], "beta": float(self.beta), "curve": self.curve, "lam": self.lam}

    @staticmethod
    def from_dict(d: dict) -> "StabilityModel":
        return StabilityModel(features=d["features"], w=np.array(d["w"]), beta=d["beta"], curve=d["curve"], lam=d["lam"])

    def __call__(self, *a, **k):  # pragma: no cover
        return self.predict(*a, **k)

    def stability_scalar(self, x: dict) -> float:
        """Convenience for the app: x maps feature name -> value."""
        v = np.array([[x[f] for f in self.features]]) if self.features else np.zeros((1, 0))
        return float(self.stability(v)[0])
