# REMEM

REMEM is a personalised revision scheduler. A student adds study notes (or picks a ready-made topic), the app turns them into multiple-choice questions, and then tells the student **what to revise today and when to revise it next**.

The scheduling idea combines three parts:

1. **Mastery** of each concept, estimated with Bayesian Knowledge Tracing (implemented from scratch in NumPy).
2. **Forgetting**: retrievability falls as a power law of the time since the last practice, `R = (1 + k·t/S)^(−β)`, where the stability `S` (days until recall drops to 90%) is predicted from the student's history.
3. **A threshold scheduler**: review a concept when its predicted retention falls to a target θ (default 85%).

It is evaluated three ways: a held-out calibration study on the public EdNet dataset, a simulated-student lab with known true memory (SimLab), and a small randomised live pilot. The full design, decisions and results log are in [docs/REMEM_Master_Specification_FINAL.md](docs/REMEM_Master_Specification_FINAL.md).

## What is in the repository

| Path | Purpose |
|---|---|
| `backend/` | FastAPI service: accounts, notes to quiz (Gemini), due list, answers, retention curve, SQLite storage |
| `webapp/` | Phone-first progressive web app (plain JavaScript, no build step) |
| `models/`, `scheduler/`, `baselines/` | BKT, forgetting/stability model, scheduler, SM-2 and simple baselines |
| `preprocessing/` | EdNet sampling and causal feature construction |
| `evaluation/`, `experiments/` | Metrics and one script per experiment; results in `experiments/results/` |
| `simlab/` | Simulated-student lab used to compare schedulers with known truth |
| `models/offsets.py`, `scheduler/replay.py` | Hierarchical offsets (Experiment 4) and replay checks (Experiment 6) |
| `eval_dashboard/` | Streamlit dashboard for the pilot monitor and experiment results |
| `deploy/`, `docs/DEPLOY.md` | Server setup (systemd, Caddy HTTPS, nightly backup) |
| `docs/` | Specification, deployment guide, UX audit, per-module viva notes |
| `tests/` | Unit and API tests |

## Setup (Windows PowerShell, Python 3.13)

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run the app

```powershell
copy .env.example .env          # then put your Gemini API key in .env
python -m backend.admin_create_user create user01     # prints a generated password once
python -m uvicorn backend.main:app --port 8000
```

Open http://localhost:8000. Accounts are created by the owner only (at most 10 student accounts). `python -m backend.admin_create_user --help` lists reset, disable and list actions.

## Run the dashboard

```powershell
streamlit run eval_dashboard/app.py
```

The Pilot page loads live data from the server with your admin account. Put `REMEM_SERVER_URL` and `REMEM_ADMIN_PASSWORD` in `.env` to connect automatically (otherwise a connect form appears). From the same page you can open or close the final check and reset test data (a confirmation dialog protects the reset). To keep dated backups on this computer, run `python -m eval_dashboard.pull_backup`, or schedule `deploy\pull_backup.cmd` with Windows Task Scheduler.

## Offline demo (no internet, no API key)

```powershell
python -m backend.seed_demo --password demo-pass
python -m uvicorn backend.main:app --port 8000
```
Sign in as `demo`. The account comes with the three ready-made topics, taken from the pre-written question bank in `artifacts/fallback/`, and a short study history, so the Today screen shows concepts that are due, coming up and new. The same bank is used automatically if the language model fails while a ready-made topic is being turned into a quiz (set `REMEM_FALLBACK=0` to turn that off).

## Tests

```powershell
python -m pytest tests -q
```

## Reproduce the experiments

The EdNet dataset is not included (licence and size). Download EdNet KT1 and the EdNet content files from the dataset's official site and extract them to `data/raw/EdNet-KT1/` and `data/raw/EdNet-content/`. Then, from the repository root:

```powershell
python preprocessing/build_dataset.py --sample-files 20000 --target-users 4000
python -m experiments.exp1_feasibility
python -m experiments.exp2_bkt_baseline
python -m experiments.exp3_forgetting
python -m experiments.make_starter_prior
python experiments/exp10_simlab.py
python -m experiments.exp4_personalisation
python -m experiments.exp6_replay
```

Outputs are written to `experiments/results/` (tables and a figure) and appended to `experiments/results/run_log.csv`. Fitted parameters used by the app are in `artifacts/`.

## Findings so far

- BKT without forgetting beats the majority, concept-difficulty and student-accuracy baselines on a chronological held-out split.
- On EdNet, a power-law forgetting term improves calibration over a non-forgetting model, but feature-driven personalisation adds very little. The app therefore starts from a documented prior (see the specification, decision D15).
- In SimLab, threshold scheduling matches a fixed interval that was tuned with knowledge of the true memory, and needs about half the reviews of SM-2 at the same coverage. It does not show a benefit from per-student personalisation.

These are results on simulated learners and one public dataset; they are not evidence that the app improves learning for people. The live pilot is small and is analysed descriptively.

## Data and privacy

Accounts are anonymous (no name or email). Answers and review times are stored to evaluate the scheduler. Notes are sent to Google Gemini to generate questions, so users are asked not to paste personal or confidential text. Raw data, the database, `.env` and keys are excluded from version control.
