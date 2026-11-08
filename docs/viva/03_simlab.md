# Viva note 3 - SimLab (Experiment 10)

**Why a simulator?** Logs cannot say what would have happened under a different review schedule. In a simulator the true memory is known, so any scheduler can be run closed-loop and judged against truth.

**What is simulated.** Per student-concept pair: latent knowledge (BKT-like: known with p=0.45 after first exposure, learns with p=0.20 per review), true stability S_true (log-normal from student ability, concept difficulty, noise), a true recall curve (Gen-1 power, Gen-2 exponential, Gen-3 mixture). Success multiplies S_true by 1+phi(1-r) (harder reviews help more); failure multiplies by 0.6. Policies see only right/wrong answers.

**Who competes.** REMEM (features), REMEM-global (one S), REMEM with the starter prior, SM-2 (with an interval multiplier as a knob), fixed intervals. REMEM's parameters are fitted on a *separate training cohort* run under random 1-14 day intervals, so it is never given the truth.

**How "fair" is compared.** Each baseline's knob is tuned (bisection) so its time spent below 85% true recall equals REMEM(theta=0.85)'s. Then compare reviews performed.

**Result (honest).** REMEM = best tuned fixed interval (-2% to 0%, inside seed range). About 47% fewer reviews than SM-2 at the same coverage. Holds under Gen-2/Gen-3. Feature personalisation adds nothing measurable; S recovery is poor.

**Likely questions.**
- *Isn't this rigged?* The mis-specified generators and training on a separate cohort are the guard; the headline is stated as "matches tuned fixed", not "wins".
- *Why is SM-2 so much worse?* Its interval grows 1, 6, x2.5 quickly; here S is about 5 days and the horizon 60 days, and it has no notion of target retention.
- *What does it mean for real students?* Nothing is proven; the pilot is descriptive and calibration on real data is the real-world check.
- *Why match on time-below-target?* Mean recall at review time rewards policies that review rarely at high recall; coverage over time is what a learner experiences.
