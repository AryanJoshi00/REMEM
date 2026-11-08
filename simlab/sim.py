"""SimLab (spec 16): simulated students with KNOWN true memory, used to compare review schedulers in a closed loop.

Truth (hidden from every policy): per student-concept pair a stability S_true (days until true recall = 0.9),
a recall curve family (gen1 power / gen2 exponential / gen3 mixture), and update rules for success and failure.
Policies only ever see the simulated right/wrong answers.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np

from baselines.sm2 import SM2State, sm2_update
from models.bkt import BKTParams, update_mastery
from models.stability import StabilityModel
from scheduler.scheduler import t_review_days

GUESS, SLIP = 0.25, 0.10
L0_TRUE, T_TRUE = 0.45, 0.20       # true learning dynamics (BKT in the policies uses slightly different values)
BKT = BKTParams(L0=0.3, T=0.15, G=GUESS, S=SLIP)       # same shape as the deployed notes parameters
ABILITY_GAMMA = 0.9
BETA_TRUE = 0.5
K_TRUE = 0.9 ** (-1 / BETA_TRUE) - 1
HORIZON_DAYS = 60.0
T_MIN, T_MAX = 1.0, 180.0


# ------------------------------------------------------------------ true forgetting curves
def _mix_raw(x):          # fast + slow exponential component, x = dt / S before calibration
    return 0.55 * np.exp(-x / 0.35) + 0.45 * np.exp(-x / 6.0)


def _solve_mix_scale():
    """Scale c such that the mixture equals 0.9 at dt = S, so all three families share the meaning of S."""
    lo, hi = 1e-6, 10.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if _mix_raw(mid) > 0.9 else (lo, mid)
    return 0.5 * (lo + hi)


_C_MIX = _solve_mix_scale()


def true_recall(dt, S, gen: str):
    dt = np.asarray(dt, float)
    if gen == "gen1":                                       # power-law, matched to REMEM's form
        return (1 + K_TRUE * dt / S) ** (-BETA_TRUE)
    if gen == "gen2":                                       # exponential (mis-specified for REMEM)
        return 0.9 ** (dt / S)
    if gen == "gen3":                                       # mixture of exponentials (mis-specified)
        return _mix_raw(dt / S * _C_MIX)
    raise ValueError(gen)


def xstar(gen: str, target: float) -> float:
    """dt/S at which true recall first falls below `target` (all families depend on dt/S only)."""
    lo, hi = 0.0, 1e4
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if float(true_recall(mid, 1.0, gen)) > target else (lo, mid)
    return 0.5 * (lo + hi)


# ------------------------------------------------------------------ cohort
@dataclass
class Cohort:
    n_students: int
    n_concepts: int
    seed: int
    ability: np.ndarray = field(init=False)           # true student trait
    S0: np.ndarray = field(init=False)                # (students, concepts) initial true stability (days)
    t0: np.ndarray = field(init=False)                # first-exposure time (days)

    def __post_init__(self):
        rng = np.random.default_rng(self.seed)
        self.ability = rng.normal(0, 1, self.n_students)
        diff = rng.normal(0, 1, (self.n_students, self.n_concepts))
        noise = rng.normal(0, 0.3, (self.n_students, self.n_concepts))
        self.S0 = np.exp(np.log(3.0) + 0.5 * self.ability[:, None] - 0.4 * diff + noise)
        self.t0 = rng.uniform(0, 7.0, (self.n_students, self.n_concepts))


# ------------------------------------------------------------------ policies (see only answers)
class Policy:
    name = "policy"

    def first(self, sid) -> None: ...
    def answer(self, sid, cid, t, correct: int, first: bool, rng) -> float:
        """Record an answer and return the interval (days) until the next review."""
        raise NotImplementedError


class FixedPolicy(Policy):
    def __init__(self, days: float):
        self.days = days
        self.name = f"fixed_{days:g}d"

    def answer(self, sid, cid, t, correct, first, rng):
        return self.days


class SM2Policy(Policy):
    def __init__(self, mult: float = 1.0):
        self.mult = mult
        self.name = "sm2" if mult == 1.0 else f"sm2_x{mult:.2f}"
        self.st: dict = {}

    def answer(self, sid, cid, t, correct, first, rng):
        s = self.st.get((sid, cid), SM2State())
        q = (5 if rng.random() < 0.5 else 4) if correct else 2      # no response times in SimLab: random fast/slow split
        s = sm2_update(s, q)
        self.st[(sid, cid)] = s
        return float(np.clip(s.interval_days * self.mult, T_MIN, T_MAX))


class RememPolicy(Policy):
    """Mastery by BKT, S from the stability model's feature regression, interval by inverting the power curve at theta."""

    def __init__(self, model: StabilityModel, theta: float, label: str):
        self.model, self.theta = model, theta
        self.name = f"{label}_th{theta:.2f}"
        self.m: dict = {}
        self.n: dict = {}
        self.ability: dict = {}
        self.S_hat_log: list = []           # (sid, cid, S_hat) for estimator recovery

    def features(self, m, n, ability):
        vals = {"m": m, "log_n": float(np.log1p(n)), "ability": ability, "difficulty": 0.33, "rt_z": 0.0}
        return vals

    def answer(self, sid, cid, t, correct, first, rng):
        key = (sid, cid)
        m = update_mastery(BKT.L0 if first else self.m[key], int(correct), BKT)
        n = self.n.get(key, 0) + 1
        a = ABILITY_GAMMA * self.ability.get(sid, 0.67) + (1 - ABILITY_GAMMA) * float(correct)
        self.m[key], self.n[key], self.ability[sid] = m, n, a
        S = self.model.stability_scalar(self.features(m, n, a))
        self.S_hat_log.append((sid, cid, S))
        return t_review_days(S, self.model.beta, self.theta, T_MIN, T_MAX)


class RandomPolicy(Policy):
    """Neutral schedule used only to generate the training cohort (log-uniform 1-14 days)."""
    name = "neutral_random"

    def __init__(self):
        self.rows: list = []
        self.m: dict = {}
        self.n: dict = {}
        self.ability: dict = {}
        self.last: dict = {}

    def answer(self, sid, cid, t, correct, first, rng):
        key = (sid, cid)
        m_prev = None if first else self.m[key]
        if not first:                                             # a labelled review row: features from the PREVIOUS post-update state
            prev = self.last[key]
            self.rows.append((t - prev["t"], prev["m"], prev["logn"], prev["a"], int(correct)))
        m = update_mastery(BKT.L0 if first else m_prev, int(correct), BKT)
        n = self.n.get(key, 0) + 1
        a = ABILITY_GAMMA * self.ability.get(sid, 0.67) + (1 - ABILITY_GAMMA) * float(correct)
        self.m[key], self.n[key], self.ability[sid] = m, n, a
        self.last[key] = {"t": t, "m": m, "logn": float(np.log1p(n)), "a": a}
        return float(np.exp(rng.uniform(np.log(1.0), np.log(14.0))))


# ------------------------------------------------------------------ closed loop
@dataclass
class Result:
    reviews_per_concept: np.ndarray       # per student
    recall_at_review: np.ndarray          # per student: mean true recall at review time
    frac_below: np.ndarray                # per student: share of tracked time with true recall < target
    final_recall: np.ndarray              # per student: mean true recall at horizon
    s_true_hat: np.ndarray | None = None  # (n, 2) true S vs estimated S after each REMEM update


def simulate(cohort: Cohort, policy: Policy, gen: str, phi: float = 1.5, rho: float = 0.6, horizon: float = HORIZON_DAYS,
             target: float = 0.85, seed: int = 0) -> Result:
    ns, nc = cohort.n_students, cohort.n_concepts
    heap = [(float(cohort.t0[s, c]), s, c) for s in range(ns) for c in range(nc)]
    heapq.heapify(heap)
    S = cohort.S0.copy()
    xs = xstar(gen, target)
    known = np.zeros((ns, nc), bool)
    last = np.full((ns, nc), np.nan)
    rev_n = np.zeros(ns); rec_sum = np.zeros(ns); below_t = np.zeros(ns); tracked_t = np.zeros(ns)
    rngs: dict = {}
    est = []
    while heap:
        t, s, c = heapq.heappop(heap)
        if t > horizon:
            continue
        rng = rngs.setdefault((s, c), np.random.default_rng([seed, s, c, 7]))
        first = np.isnan(last[s, c])
        if first:
            known[s, c] = rng.random() < L0_TRUE                      # latent knowledge after first exposure (BKT-consistent story)
            r = 1.0 if known[s, c] else 0.0
            correct = int(rng.random() < GUESS + (1 - GUESS - SLIP) * r)
        else:
            dt = t - last[s, c]
            r_mem = float(true_recall(dt, S[s, c], gen))
            r = r_mem if known[s, c] else 0.0
            correct = int(rng.random() < GUESS + (1 - GUESS - SLIP) * r)
            r = r_mem                                               # reported "true recall" is the memory trace, as in the spec
            rev_n[s] += 1; rec_sum[s] += r
            # time spent below target in (last, t): exact by grid
            below_t[s] += max(dt - S[s, c] * xs, 0.0)
            tracked_t[s] += dt
            if not known[s, c]:
                known[s, c] = rng.random() < T_TRUE                 # learning transition on an unknown concept
            elif correct:
                S[s, c] = S[s, c] * (1 + phi * (1 - r))
            else:
                S[s, c] = max(S[s, c] * rho, 0.05)
        interval = policy.answer(s, c, t, correct, bool(first), rng)
        if isinstance(policy, RememPolicy) and policy.S_hat_log:
            est.append((S[s, c], policy.S_hat_log[-1][2]))
        last[s, c] = t
        heapq.heappush(heap, (t + max(interval, 1e-3), s, c))
    # close out: time from last review to horizon, and delayed-test recall at the horizon
    final = np.zeros(ns)
    for s in range(ns):
        rs = []
        for c in range(nc):
            if np.isnan(last[s, c]):
                continue
            dt = max(horizon - last[s, c], 0.0)
            rs.append(float(true_recall(dt, S[s, c], gen)))
            below_t[s] += max(dt - S[s, c] * xs, 0.0)
            tracked_t[s] += dt
        final[s] = np.mean(rs) if rs else np.nan
    with np.errstate(invalid="ignore", divide="ignore"):
        return Result(rev_n / nc, rec_sum / np.maximum(rev_n, 1), below_t / np.maximum(tracked_t, 1e-9), final,
                      np.array(est) if est else None)


# ------------------------------------------------------------------ REMEM fitting on a neutral training cohort
def fit_remem_model(gen: str, seed: int, n_students: int = 150, n_concepts: int = 8, phi: float = 1.5,
                    features=("m", "log_n", "ability")) -> StabilityModel:
    coh = Cohort(n_students, n_concepts, seed=10_000 + seed)
    pol = RandomPolicy()
    simulate(coh, pol, gen, phi=phi, seed=10_000 + seed)
    rows = np.array(pol.rows)
    dt, m, logn, a, y = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3], rows[:, 4]
    cols = {"m": m, "log_n": logn, "ability": a}
    X = np.column_stack([cols[f] for f in features]) if features else np.zeros((len(y), 0))
    mdl = StabilityModel(features=list(features), beta=0.5, curve="power")
    mdl.fit(dt, X, m, GUESS, SLIP, y)
    return mdl
