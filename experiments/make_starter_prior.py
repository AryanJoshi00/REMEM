"""Build the deployed 'starter prior' stability model used by the app for brand-new notes concepts.

Why not deploy the EdNet fit directly? (Experiment 3, see docs/viva/02_forgetting_model.md)
  * EdNet's fitted curve is extremely flat (beta ~ 0.02, S ~ 100 days) - it describes English-test practice, not notes quizzes.
  * Repetition and mastery coefficients are not identifiable there (hard concepts get re-served: selection effect).
So the deployed model keeps the model STRUCTURE and the EdNet-supported ability/difficulty effects, but sets the
absolute time scale and repetition growth from an FSRS-style prior (beta = 0.5, R(S) = 0.9). The pilot then
tests this prior (Experiment 11) and a labelled refit on pilot data is reported.

Assumptions (all explicit, all to be re-estimated from pilot data):
  A1 beta = 0.5                        (FSRS-4.5/5 power-law decay exponent)
  A2 w_m = 0.8, w_log_n = 0.9          (mastery and spaced repetition lengthen stability; Loftus 1985)
  A3 w_ability, w_difficulty from the EdNet fit (Experiment 3)
  A4 intercept chosen so a typical first review has S ~ 2.5 days
  A5 BKT for brand-new notes concepts: L0 = 0.3, T = 0.15, G = 0.25 (4-option MCQ), S = 0.10
     (EdNet pooled L0 = 0.74 describes practised test-takers, not students meeting new material)
"""
import json
from pathlib import Path

import numpy as np

ART = Path(__file__).resolve().parents[1] / "artifacts"
ed = json.loads((ART / "stability_model_ednet.json").read_text())
w_ed = dict(zip(["intercept"] + ed["features"], ed["w"]))
features = ["m", "log_n", "ability", "difficulty", "rt_z"]
w = {"m": 0.8, "log_n": 0.9, "ability": w_ed["ability"], "difficulty": w_ed["difficulty"], "rt_z": 0.0}
typical = {"m": 0.6, "log_n": np.log1p(1), "ability": 0.67, "difficulty": 0.33, "rt_z": 0.0}
w0 = float(np.log(2.5) - sum(w[f] * typical[f] for f in features))
out = {"features": features, "w": [w0] + [float(w[f]) for f in features], "beta": 0.5, "curve": "power", "lam": 0.0,
       "source": "starter prior (FSRS-style scale) + EdNet ability/difficulty effects; see make_starter_prior.py"}
(ART / "stability_model.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))

(ART / "bkt_notes.json").write_text(json.dumps({"L0": 0.3, "T": 0.15, "G": 0.25, "S": 0.10, "source": "assumption A5"}, indent=2))
print("wrote bkt_notes.json")
