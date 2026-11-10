# Viva note 7 - Concept-linked failure feature (Experiment 9)

**Idea.** If a student has just failed concept A, are they also more likely to forget concept B when A and B are related? The feature `F` adds up a student's recent failures on related concepts, each fading with time: `F = sum over related concepts c' of w(c, c') x sum over earlier failures on c' of exp(-(t - t_fail) / tau)`. The model learns whether `F` shortens or lengthens memory strength (the sign is not assumed).

**Where the links come from.** A co-error correlation measured on the training period only: for each concept pair, correlate across students the amount by which each student's error rate on the concept exceeds their own overall error rate. Negative or unsupported pairs are dropped, each concept keeps its top neighbours, and weights are scaled to 0-1. It is not a hand-made prerequisite graph, and it is never called "prerequisite".

**Causality.** `F` for an answer uses only that student's earlier answers on other concepts. The running decayed failure sum is updated after the answer is scored. This is tested (own outcome, own concept, equal timestamps, row order, separate students).

**Result (honest).**
- Settings chosen on validation: 15 neighbours, fading over 1 day (both at the edge of the grid that was tried: k in {5, 15}, tau in {1, 7} days).
- On held-out repeat answers: log loss improves by 0.0019 (95% interval 0.0013 to 0.0025), ECE 0.041 to 0.035; for gaps of a day or more 0.0022 (0.0016 to 0.0028). This is the largest gain of any extension so far (offsets: 0.0007).
- The learned weight is negative: a recent failure on a related concept shortens predicted memory strength.
- **Controls:** the same feature with links shuffled across concepts gains 0.0006 to 0.0009; with every concept equally linked 0.0010. The real links beat every control (by 0.0010 to 0.0013, intervals above zero). So about half of the gain is a general "student is having a bad stretch" signal and the rest depends on which concepts are linked.

**What to say if asked.**
- *Why the controls?* The first run gave a larger gain than expected and 81% of test rows had some recent failure. Controls were added after seeing that; the rule for calling the effect specific (real links beat every control with an interval above zero) was written before the controls were run.
- *Why is the feature not in the app?* EdNet's concepts are numbered tags and the app's concepts come from pasted notes, so no co-error data exists for them. The spec's plan for notes (embedding similarity of concept names) is not built, and the fitted EdNet curve is nearly flat anyway (decision D21).
- *Is it a causal effect?* No. It is a predictive association in observational data.
- *Hard window?* No: exponential decay replaces the window, which keeps the computation a single pass.
