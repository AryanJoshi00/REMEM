# Viva note 5 - Scheduler replay checks (Experiment 6)

**Question.** Offline, on logged answers, can we say anything about the schedule REMEM would recommend? Two honest checks:
1. **Calibration at recommended times.** For each logged review, compute the recommended gap at the 85% target from the state before it. Group reviews by actual gap / recommended gap. If the predicted chance of a correct answer matches what happened for reviews near the recommendation, the predictions the schedule relies on can be trusted.
2. **Target sweep.** For targets 0.75 to 0.95: the recommended gaps, how many are clipped by the 1-day and 180-day limits, the implied reviews per concept-month, and how many real reviews fell near the recommendation.

**What it is not.** It is not evidence that following the schedule helps learning. Everything is judged by REMEM's own model, so it is circular for that question. That claim rests on SimLab (known truth) and the live pilot.

**Results.** The EdNet-fitted curve (beta 0.022) is almost flat: it recommends the 180-day maximum for most targets, so it cannot schedule. The deployed starter prior recommends gaps of days to weeks (median 19 days at 85%; 1.2 reviews per concept-month at 0.75 up to 8.3 at 0.95). Near the recommendation its predictions are not well calibrated (calibration error 0.067 within 0.5x to 2x; threshold 0.05): too optimistic for early reviews, too pessimistic for very late ones. So the recommendations are flagged unreliable on EdNet.

**Things to say if asked.**
- *The verdict rule changed?* Yes, and it is disclosed: it was first written on the narrow "on time" band (0.8-1.25x), where the prior passes (ECE 0.042); it was widened to 0.5-2x for more reviews, where it fails (0.067). Both are reported; the wider band is the verdict.
- *Why does the app still use the prior?* The fitted curve is unusable; the prior is a documented starting point (D15) and the pilot measures its calibration on real study notes.
- *Is EdNet the right test?* It is English test practice, not study notes, so a poor result there is a warning, not a verdict on the pilot.
