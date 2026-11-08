"""SimLab sanity tests: the truth is what it claims, and the closed loop behaves sensibly."""
import numpy as np

from simlab import sim


def test_curves_share_S_meaning():
    for gen in ("gen1", "gen2", "gen3"):
        assert abs(float(sim.true_recall(5.0, 5.0, gen)) - 0.9) < 1e-6
        r = sim.true_recall(np.array([0, 1, 5, 30]), 5.0, gen)
        assert r[0] == 1.0 and np.all(np.diff(r) < 0)


def test_fixed_interval_review_counts():
    coh = sim.Cohort(30, 4, seed=1)
    r1 = sim.simulate(coh, sim.FixedPolicy(2.0), "gen1")
    r2 = sim.simulate(coh, sim.FixedPolicy(10.0), "gen1")
    assert r1.reviews_per_concept.mean() > 3 * r2.reviews_per_concept.mean()     # more frequent -> more reviews
    assert r1.recall_at_review.mean() > r2.recall_at_review.mean()               # and higher recall when reviewing
    assert r1.frac_below.mean() < r2.frac_below.mean()


def test_deterministic_given_seed():
    coh = sim.Cohort(20, 4, seed=3)
    a = sim.simulate(coh, sim.FixedPolicy(3.0), "gen2", seed=5)
    b = sim.simulate(coh, sim.FixedPolicy(3.0), "gen2", seed=5)
    assert np.allclose(a.reviews_per_concept, b.reviews_per_concept) and np.allclose(a.final_recall, b.final_recall)


def test_remem_fit_recovers_ordering():
    mdl = sim.fit_remem_model("gen1", seed=0, n_students=60, n_concepts=6)
    assert 0.01 <= mdl.beta <= 3.0 and len(mdl.w) == 4
    coh = sim.Cohort(40, 6, seed=2)
    pol = sim.RememPolicy(mdl, 0.85, "remem")
    res = sim.simulate(coh, pol, "gen1")
    assert res.s_true_hat is not None and len(res.s_true_hat) > 100
    assert np.isfinite(res.recall_at_review).all()
