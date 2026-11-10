"""Concept-linked failure feature (spec 9.5): causal, decaying, excludes the concept itself, independent of row order."""
import numpy as np
import pandas as pd

from models.links import link_feature, neighbour_weights, similarity_matrix

DAY = 86_400_000


def events(rows):
    return pd.DataFrame(rows, columns=["student_id", "concept_id", "timestamp", "correct"])


def W2():
    W = np.zeros((3, 3))
    W[1, 0] = 1.0                      # failing concept 0 matters for concept 1
    W[0, 1] = 0.5
    return W


def test_failure_on_a_related_concept_raises_F_and_it_decays():
    ids = [0, 1, 2]
    d = events([("a", 0, 0, 0), ("a", 1, 0.1 * DAY, 1), ("a", 1, 3 * DAY, 1), ("a", 2, 3 * DAY + 1, 1)])
    F = link_feature(d, W2(), ids, tau_days=3.0)
    assert F[0] == 0.0                                                   # nothing earlier
    assert np.isclose(F[1], np.exp(-0.1 / 3.0), atol=1e-9)               # failed concept 0 a moment ago
    assert F[2] < F[1] and np.isclose(F[2], np.exp(-3.0 / 3.0), atol=1e-9)   # decays with time
    assert F[3] == 0.0                                                   # concept 2 has no links


def test_own_outcome_and_own_concept_never_count():
    ids = [0, 1, 2]
    d = events([("a", 1, 0, 0), ("a", 1, DAY, 0), ("a", 0, 2 * DAY, 1)])
    F = link_feature(d, W2(), ids, 3.0)
    assert F[0] == 0.0 and F[1] == 0.0                                   # failures on concept 1 itself do not feed concept 1 (diagonal is 0)
    assert np.isclose(F[2], 0.5 * (np.exp(-2.0 / 3.0) + np.exp(-1.0 / 3.0)))       # but they do feed concept 0 (weight 0.5), earlier rows only


def test_students_are_independent_and_row_order_does_not_matter():
    ids = [0, 1, 2]
    d = events([("a", 0, 0, 0), ("b", 1, 0, 1), ("a", 1, DAY, 1), ("b", 1, DAY, 1)])
    F = link_feature(d, W2(), ids, 3.0)
    assert F[2] > 0 and F[3] == 0.0                                      # student b never failed concept 0
    shuffled = d.sample(frac=1.0, random_state=0)
    Fs = link_feature(shuffled, W2(), ids, 3.0)
    assert np.allclose(pd.Series(Fs, index=shuffled.index).sort_index().to_numpy(), F)


def test_strictly_earlier_equal_timestamps_do_not_see_each_other_when_ordered_first():
    ids = [0, 1, 2]
    d = events([("a", 0, DAY, 0), ("a", 1, DAY, 1)])                     # same timestamp: processed in row order, the second sees the first
    F = link_feature(d, W2(), ids, 3.0)
    assert F[0] == 0.0 and np.isclose(F[1], 1.0)


def test_similarity_finds_a_planted_pair_and_neighbour_weights_keep_top_k():
    rng = np.random.default_rng(0)
    rows = []
    for s in range(300):
        skill = rng.normal()
        for c in range(6):
            p_err = np.clip(0.4 - 0.15 * skill * (c in (0, 1)) + rng.normal(0, 0.05), 0.02, 0.98)       # concepts 0 and 1 share the student's skill
            for _ in range(40):
                rows.append((f"s{s}", c, 0, int(rng.random() > p_err)))
    d = events(rows)
    corr = similarity_matrix(d, list(range(6)))
    assert corr[0, 1] > 0.2 and corr[0, 1] == corr[1, 0] and np.all(np.diag(corr) == 0)
    assert corr[0, 1] > max(corr[0, 2:].max(), 0.0)
    W = neighbour_weights(corr, k=1, threshold=0.1)
    assert (W[0] > 0).sum() == 1 and W[0, 1] > 0 and W.max() == 1.0
