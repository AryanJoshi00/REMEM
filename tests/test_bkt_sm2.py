import numpy as np
import pytest

from baselines.sm2 import SM2State, fixed_interval, quality_from_response, sm2_update
from models.bkt import BKTParams, filter_batch, fit_bkt, p_correct, pad_sequences, update_mastery

PRM = BKTParams(L0=0.3, T=0.1, G=0.2, S=0.1)


def test_bkt_update_correct_matches_hand_calculation():
    # posterior = .3*.9 / (.3*.9 + .7*.2) = 0.658537 ; after learning = .658537 + .341463*.1
    assert update_mastery(0.3, 1, PRM) == pytest.approx(0.692683, abs=1e-5)


def test_bkt_update_incorrect_matches_hand_calculation():
    # posterior = .3*.1 / (.3*.1 + .7*.8) = 0.050847 ; after learning = .050847 + .949153*.1
    assert update_mastery(0.3, 0, PRM) == pytest.approx(0.145763, abs=1e-5)


def test_p_correct_formula():
    assert p_correct(0.5, PRM) == pytest.approx(0.5 * 0.9 + 0.5 * 0.2)


def test_filter_batch_matches_stepwise_and_stays_in_unit_interval():
    seq = np.array([1, 1, 0, 1, 0, 0, 1])
    Y, M = pad_sequences([seq, seq[:3]])
    prior, post, ll = filter_batch(Y, M, PRM)
    p = PRM.L0
    for t, y in enumerate(seq):
        assert prior[0, t] == pytest.approx(p)
        p = update_mastery(p, int(y), PRM)
        assert post[0, t] == pytest.approx(p)
    assert np.isfinite(ll) and ll < 0
    assert ((prior >= 0) & (prior <= 1)).all() and ((post >= 0) & (post <= 1)).all()
    # padded (masked) steps must not move the state of the short sequence
    assert post[1, 5] == pytest.approx(post[1, 2])


def test_prior_does_not_depend_on_own_label():
    seq = np.array([1, 0, 1, 1])
    flipped = seq.copy(); flipped[2] = 0
    a = filter_batch(*pad_sequences([seq]), PRM)[0]
    b = filter_batch(*pad_sequences([flipped]), PRM)[0]
    assert a[0, 2] == pytest.approx(b[0, 2])     # prior at t=2 unchanged
    assert a[0, 3] != pytest.approx(b[0, 3])     # later prior changes


def test_fit_bkt_recovers_synthetic_parameters_roughly():
    rng = np.random.default_rng(0)
    true = BKTParams(0.3, 0.15, 0.2, 0.1)
    seqs = []
    for _ in range(1500):
        k = rng.random() < true.L0
        y = []
        for _ in range(20):
            y.append(int(rng.random() < (1 - true.S if k else true.G)))
            k = k or (rng.random() < true.T)
        seqs.append(np.array(y))
    est = fit_bkt(seqs, n_starts=3, seed=1)
    assert abs(est.G - true.G) < 0.08 and abs(est.S - true.S) < 0.08 and abs(est.T - true.T) < 0.08


def test_sm2_known_sequence():
    s = SM2State()
    s = sm2_update(s, 5); assert (s.reps, s.interval_days) == (1, 1.0) and s.ef == pytest.approx(2.6)
    s = sm2_update(s, 5); assert (s.reps, s.interval_days) == (2, 6.0) and s.ef == pytest.approx(2.7)
    s = sm2_update(s, 5); assert s.reps == 3 and s.interval_days == 17.0 and s.ef == pytest.approx(2.8)


def test_sm2_failure_resets_and_ef_floor():
    s = sm2_update(SM2State(ef=1.35, reps=4, interval_days=30), 2)
    assert s.reps == 1 and s.interval_days == 1.0 and s.ef >= 1.3


def test_quality_mapping_and_fixed_interval():
    assert quality_from_response(True, 1000, 2000) == 5
    assert quality_from_response(True, 3000, 2000) == 4
    assert quality_from_response(False, 100, 2000) == 2
    assert fixed_interval() == 3.0
