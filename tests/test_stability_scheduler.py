import numpy as np
import pytest

from models.stability import (StabilityModel, k_of_beta, predict_p, retrievability_exp, retrievability_power)
from scheduler.scheduler import build_due_list, current_R, t_review_days


@pytest.mark.parametrize("beta", [0.2, 0.5, 1.0, 2.0])
def test_retrievability_is_090_at_S(beta):
    assert retrievability_power(7.0, 7.0, beta) == pytest.approx(0.9)
    assert retrievability_exp(7.0, 7.0) == pytest.approx(0.9)


def test_retrievability_monotone_and_bounded():
    dt = np.linspace(0, 400, 200)
    R = retrievability_power(dt, 10.0, 0.4)
    assert R[0] == pytest.approx(1.0) and (np.diff(R) < 0).all() and ((R > 0) & (R <= 1)).all()


def test_k_of_beta_positive():
    assert all(k_of_beta(b) > 0 for b in (0.1, 0.5, 2.0))


def test_forgetting_wraps_bkt_probability():
    p0 = predict_p(0.8, 1.0, guess=0.2, slip=0.1)
    assert p0 == pytest.approx(0.8 * 0.9 + 0.2 * 0.2)           # R = 1 => plain BKT
    p_far = predict_p(0.8, 0.0, guess=0.2, slip=0.1)
    assert p_far == pytest.approx(0.2)                           # all knowledge forgotten => guess rate
    assert 0 < predict_p(0.5, 0.6, 0.25, 0.1) < 1


@pytest.mark.parametrize("theta", [0.7, 0.85, 0.95])
def test_t_review_inverts_curve(theta):
    S, beta = 12.0, 0.45
    t = t_review_days(S, beta, theta, t_min=0.0001, t_max=1e6)
    assert retrievability_power(t, S, beta) == pytest.approx(theta, abs=1e-9)


def test_t_review_respects_bounds_and_theta_monotone():
    assert t_review_days(0.01, 0.4) == 1.0           # clipped up to t_min
    assert t_review_days(5000, 0.4) == 180.0         # clipped down to t_max
    lo = t_review_days(10, 0.4, 0.95); hi = t_review_days(10, 0.4, 0.75)
    assert lo < hi                                   # stricter target => earlier review


def test_t_review_rejects_bad_theta():
    with pytest.raises(ValueError):
        t_review_days(10, 0.4, 1.0)


def test_due_list_sorted_by_ascending_R_and_status():
    items = [{"concept_id": "a", "S_days": 30, "last_days": 0.0},
             {"concept_id": "b", "S_days": 2, "last_days": 0.0},
             {"concept_id": "c", "S_days": 10, "last_days": 9.5}]
    out = build_due_list(items, beta=0.4, now_days=10.0)
    assert [d.concept_id for d in out] == ["b", "a", "c"]
    assert all(out[i].R_now <= out[i + 1].R_now for i in range(2))
    assert out[0].due_in_days <= 0 and out[2].due_in_days > 0


def test_model_recovers_planted_stability_on_synthetic_data():
    rng = np.random.default_rng(0)
    n = 40000
    m = rng.uniform(0.3, 0.95, n); A = rng.uniform(0.2, 0.9, n)
    X = np.column_stack([m, A])
    true_w = np.array([np.log(4.0), 0.8, 1.5]); beta = 0.4
    S = np.exp(true_w[0] + X @ true_w[1:])
    dt = rng.exponential(5.0, n)
    p = predict_p(m, retrievability_power(dt, S, beta), 0.2, 0.1)
    y = (rng.random(n) < p).astype(float)
    mdl = StabilityModel(features=["m", "ability"], lam=1e-5).fit(dt, X, m, 0.2, 0.1, y, maxiter=200)
    assert abs(mdl.w[2] - 1.5) < 0.6            # ability coefficient recovered with the right sign and size
    assert mdl.w[1] > 0 and 0.15 < mdl.beta < 1.2


def test_current_R_decreases_with_time():
    assert current_R(10, 0.4, 1) > current_R(10, 0.4, 30)
