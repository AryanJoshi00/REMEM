# Viva note 4 - Personalisation by hierarchical offsets (Experiment 4)

**Idea.** The global model gives every student-concept pair the same recipe for memory strength S. Offsets add a small correction: `log S = base + u_concept + u_student + u_pair`. Each offset has a Gaussian prior around zero (a ridge penalty), so a pair with few answers stays near the concept/student average and a pair with many answers can move away from it. This is empirical-Bayes shrinkage in a form that is easy to explain.

**How it is fitted (backfitting, one pass).** Fit the global weights first (Experiment 3). Then estimate all concept offsets with the others held fixed, then all student offsets, then all pair offsets. Each group's offset is one penalised Newton step (repeated three times): `u <- u - (gradient + u/tau^2) / (curvature + 1/tau^2)`. The step is vectorised over groups with `bincount`. A group never seen in training has offset 0, so cold start needs no special code.

**What was measured.** Held-out repeat answers of the test split, overall and split by how many earlier answers the pair had in training. The prior widths `tau` were chosen level by level on the validation split.

**Result (honest).** Small gains at every level (log loss 0.6345 to 0.6338, ECE 0.041 to 0.039), mostly from student offsets. Shrinkage beats unshrunk pair fitting for pairs with up to 10 earlier answers, by tiny amounts, and is slightly worse from 11 answers. The chosen student and pair widths were at the top of the grid: validation prefers almost no shrinkage, because the fitted EdNet curve is almost flat, so big changes in S barely move predictions. Not deployed.

**Likely questions.**
- *Why not just fit one parameter per pair?* Most pairs have a handful of answers; unshrunk estimates are noisy. The stratified table shows the shrunk version is better exactly there, though only slightly.
- *Why is the effect so small?* The EdNet forgetting curve is nearly flat (beta 0.022), so memory strength hardly affects the predicted probability. The offsets mostly absorb concept and student level differences.
- *Is the personalisation claim still alive?* Narrowed: small but consistent offline gains. SimLab also showed no benefit from feature personalisation. The pilot is descriptive only.
- *Why is the selected tau at the edge of the grid?* Stated openly; extending the grid would give a nearly unshrunk fit, which the comparison with the unshrunk model already covers.
- *Why not online updates in the app?* The gains are too small to justify more moving parts in the live system (decision D20).
