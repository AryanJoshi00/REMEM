"""Replay checks (Experiment 6): the vectorised recommendation equals the scheduler's, timing buckets partition the data."""
import numpy as np
import pandas as pd
import pytest

from models.stability import StabilityModel
from scheduler.replay import RATIO_LABELS, THETAS, predicted_p, recommended_gap_days, stability_for, theta_sweep, timing_calibration
from scheduler.scheduler import t_review_days


@pytest.mark.parametrize("beta", [0.05, 0.5, 1.2])
@pytest.mark.parametrize("theta", [0.75, 0.85, 0.95])
def test_vectorised_gap_matches_scalar_scheduler(beta, theta):
    S = np.array([0.3, 1.0, 5.0, 40.0, 800.0])
    v = recommended_gap_days(S, beta, theta)
    assert np.allclose(v, [t_review_days(s, beta, theta) for s in S])
    assert v.min() >= 1.0 and v.max() <= 180.0


def test_higher_theta_means_earlier_review():
    S = np.array([2.0, 10.0, 30.0])
    gaps = [recommended_gap_days(S, 0.5, th) for th in sorted(THETAS)]
    for a, b in zip(gaps, gaps[1:]):
        assert np.all(b <= a)


def test_invalid_theta_rejected():
    with pytest.raises(ValueError):
        recommended_gap_days([5.0], 0.5, 1.0)


def test_timing_buckets_partition_and_on_time_bucket():
    rec = np.full(8, 10.0)
    actual = np.array([1.0, 3.0, 6.0, 10.0, 11.0, 15.0, 30.0, 100.0])
    out = timing_calibration(actual, rec, np.full(8, 0.7), np.array([1, 0, 1, 1, 0, 1, 1, 0]))
    assert out["n"].sum() == 8 and list(out["bucket"]) == RATIO_LABELS
    on = out[out["bucket"] == "on time (0.8-1.25x)"].iloc[0]
    assert on["n"] == 2 and abs(on["observed"] - 0.5) < 1e-9
    assert abs(out["share"].sum() - 1) < 1e-9


def make_events(n=400, seed=0):
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"delta_t_days": np.exp(rng.uniform(np.log(0.5), np.log(60), n)), "m": rng.uniform(0.3, 0.95, n), "guess": 0.25, "slip": 0.1,
                         "log_n": rng.uniform(0, 3, n), "ability": rng.uniform(0.3, 0.9, n), "correct": rng.integers(0, 2, n)})


def test_theta_sweep_shape_and_rails():
    mdl = StabilityModel(features=["m", "log_n", "ability"], curve="power", beta=0.5)
    mdl.w = np.array([np.log(3.0), 0.5, 0.3, 0.2])
    d = make_events()
    sw = theta_sweep(mdl, d)
    assert list(sw["theta"]) == list(THETAS)
    assert (sw["mean_recommended_days"].diff().dropna() <= 1e-9).all()                       # higher θ -> shorter recommended gaps
    assert (sw["reviews_per_concept_month"].diff().dropna() >= -1e-9).all()                  # ... and more reviews per month
    assert ((sw["share_at_max_rail"] >= 0) & (sw["share_at_max_rail"] <= 1)).all()
    assert (sw["n_near_recommendation"] <= len(d)).all()
    assert np.allclose(stability_for(mdl, d), np.exp(mdl.w[0] + d[mdl.features].to_numpy() @ mdl.w[1:]).clip(0.05, 3650))
    p = predicted_p(mdl, d)
    assert p.min() >= 0.0 and p.max() <= 1.0
