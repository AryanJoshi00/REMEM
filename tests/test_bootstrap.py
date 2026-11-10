import numpy as np

from evaluation.bootstrap import cluster_bootstrap_diff, row_loss


def test_row_loss_matches_formula():
    assert np.isclose(row_loss([1, 0], [0.8, 0.3]), [-np.log(0.8), -np.log(0.7)]).all()


def test_clear_improvement_has_interval_above_zero_and_noise_straddles_zero():
    rng = np.random.default_rng(1)
    students = np.repeat(np.arange(200), 20)
    y = rng.integers(0, 2, len(students))
    good = np.where(y == 1, 0.8, 0.2)                    # informative predictions
    flat = np.full(len(students), 0.5)
    d = cluster_bootstrap_diff(students, row_loss(y, flat), row_loss(y, good), n_boot=300)
    assert d["lo"] > 0 and d["mean_diff"] > 0.3 and d["n_students"] == 200
    noise = rng.normal(0, 0.01, len(students))
    d2 = cluster_bootstrap_diff(students, row_loss(y, flat), row_loss(y, np.clip(flat + noise, 0.01, 0.99)), n_boot=300)
    assert d2["lo"] < 0 < d2["hi"]


def test_deterministic_for_a_seed():
    s = np.repeat(np.arange(50), 4); a = np.linspace(0.5, 0.9, 200); b = a + 0.01
    assert cluster_bootstrap_diff(s, a, b, 100, seed=3) == cluster_bootstrap_diff(s, a, b, 100, seed=3)
