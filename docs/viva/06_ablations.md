# Viva note 6 - Ablations (Experiment 7)

**Question.** Which parts of the model actually matter? Each variant removes or swaps one part and is scored on the same held-out repeat answers of the test split (297,133 answers, 802 students).

**How differences are judged.** The change in log loss from the full model, with a 95% interval from resampling students (rows from one student are correlated, so the student is the unit). A part "matters" only if the whole interval lies on the worse side of zero. Uncertainty comes from resampling students, not from refitting with other random seeds, because the fits are deterministic. The size labels (under 0.0005 negligible, under 0.002 small) are a reading aid, not a decision rule.

**Results (change in log loss from the full model; positive = worse).**
| Variant | Change | Reading |
|---|---|---|
| No forgetting (knowledge tracing only) | +0.0021 | the largest effect; modelling forgetting matters |
| Exponential instead of power-law, one curve | +0.0017 | the curve shape matters |
| Exponential with student features | +0.0015 | same |
| Power-law, one curve for all (no student features) | +0.0002 | features together add little but are real |
| Without student ability | +0.0002 | negligible |
| Without response time | +0.0001 | negligible |
| Without practice count | +0.00006 | negligible |
| Without mastery | +0.00001 | negligible |
| Without question difficulty | -0.00002 | no help (slightly better without it) |
| Plus offsets (Experiment 4) | -0.0007 | helps, small |
| Plus recent failures on related concepts (Experiment 9) | -0.0019 | helps, the largest single gain |

**Say plainly.** The big levers are having a forgetting term and using the power-law curve. The student and concept features, taken one at a time, are negligible on EdNet. The two extensions help a little, the link feature most. The target-retention (theta) trade-off is Experiment 6.

**Likely questions.**
- *Why is almost everything "statistically significant" but tiny?* There are 297,133 answers, so even a 0.0001 difference has a narrow interval. That is why the size labels exist: significance is not importance.
- *Why no seeds?* The stability fits are deterministic; the randomness is in which students are in the test set, which the student bootstrap covers. The knowledge-tracing starts were fixed in Experiment 2.
- *Difficulty feature slightly hurts?* By 0.00002, which is negligible; it is kept because the spec defines it and removing it changes nothing.
- *Does this show what students should do?* No. It is about prediction on logged answers.
