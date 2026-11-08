# Viva note 01 — Data, features and leakage

**What it does.** `preprocessing/build_dataset.py` samples 20,000 of the 784,309 extracted EdNet-KT1 user files, keeps students active at least 7 days with at least 30 interactions (3,856 students, 2.15M rows, 172 concepts), derives correctness (`user_answer == correct_answer`), maps each question to **one primary concept = its rarest tag**, removes exact duplicates, and sorts by time. `preprocessing/features.py` splits the data **globally by time** (first 70% of rows = train, next 15% = validation, last 15% = test) and builds causal features.

**Why a global time split.** A random split would let the model see a student's later answers while predicting earlier ones. Students appear in both train and test (at different times) on purpose: personalisation uses a student's own earlier history.

**Why a span filter.** In the first 100-student sample most students were active under one day, so they carry no forgetting signal. Experiment 1 on the filtered sample: 39% of same-concept repeats happen after more than a day, 14.6% after a week; accuracy on repeats falls from about 70% (gap under 5 min) to about 64% (gap over 30 days). The signal exists but is modest — say so.

**Features (all use earlier rows only).**
- `ability`: EWMA (decay 0.9) of the student's past correctness, shifted by one row so a row never sees its own label; global mean until 5 prior interactions.
- `delta_t_days`: days since the previous interaction with the same concept (empty on first exposure).
- `n_sessions`: number of earlier sessions with the concept (a new session starts after a 30-minute gap), so same-sitting repeats don't inflate "repetition".
- `rt_z`: previous response-time z-score for that concept, using per-question median/IQR from **train only**.
- `concept_difficulty`: 1 − train correct rate.

**How leakage is tested.** `tests/test_leakage.py`: split cutoffs are ordered and disjoint; flipping one row's label changes **no** feature of that row or earlier rows, but does change later rows; changing val/test rows leaves every training statistic identical.

**Likely questions.** *Why not random split?* (above). *Why one concept per question?* Duplicating multi-tag rows would count one answer several times in every metric. *Why is the effect small?* Accuracy mixes question difficulty and student ability; the model adds those features, and calibration by gap bin is Experiment 3.
