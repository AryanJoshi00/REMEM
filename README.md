# REMEM

REMEM is a personalised revision scheduler. A student reads a short ready-made topic once (or pastes their own notes), the app turns it into multiple-choice questions, and then it tells the student **what to revise today and when to revise it next**. The student app is called Remem; REMEM is also the name of the scheduling method inside it.

The scheduling idea combines three parts:

1. **Mastery** of each concept, estimated with Bayesian Knowledge Tracing (implemented from scratch in NumPy).
2. **Forgetting**: retrievability falls as a power law of the time since the last practice, `R = (1 + k·t/S)^(−β)`, where the stability `S` (days until recall drops to 90%) is predicted from the student's history.
3. **A threshold scheduler**: review a concept when its predicted retention falls to a target θ (default 85%).

It is evaluated three ways: a held-out calibration study on the public EdNet dataset, a simulated-student lab with known true memory (SimLab), and a small randomised live pilot. The full design, decisions and results log are in [docs/REMEM_Master_Specification_FINAL.md](docs/REMEM_Master_Specification_FINAL.md).

## How the app works

- **Sign-up:** the owner creates each account. On first sign-in the student fills a one-minute intro form and agrees to the consent text.
- **Read, then a first quiz:** a ready-made topic is read once. Starting the quiz locks the notes until the Remem Test, so a review measures memory rather than re-reading. The first quiz asks two easier and two harder questions per concept. Pasted notes are turned into questions by Google Gemini; ready-made topics fall back to a pre-written question bank if the model is unavailable.
- **One daily test:** every concept that is due is mixed into one short test, with one easier and one harder question per concept and no concept names. Right answers are shown at the end of the test.
- **Concepts and the memory curve:** each concept shows predicted recall now, mastery, and its forgetting curve against the 85% target.
- **Reminders:** optional web push, at most one a day between 9 am and 9 pm (India time), only when something is due. The app-icon badge shows how many questions are waiting.
- **The Remem Test:** near the end of the pilot the owner opens a delayed test of three unseen questions per concept, shuffled, with no feedback until the score. It does not change any schedule.
- **Three scheduling methods, randomised per concept:** REMEM, SM-2 and a fixed 3-day gap, balanced within each student. Students never see which method a concept uses.
- **Owner's view:** an admin account sees the pilot on the phone (people, activity, the method comparison, the Remem Test and every reminder message) instead of the student app.

## What is in the repository

| Path | Purpose |
|---|---|
| `backend/` | FastAPI service: accounts and sign-up, notes to questions (Gemini, with a fallback bank), the daily test, answers, retention curves, reminders (web push), the owner's API, SQLite storage and backups |
| `webapp/` | Phone-first progressive web app (plain JavaScript, no build step, works offline for viewing and queues answers) |
| `models/`, `scheduler/`, `baselines/` | BKT, forgetting/stability model, scheduler, SM-2 and simple baselines |
| `preprocessing/` | EdNet sampling and causal feature construction |
| `evaluation/`, `experiments/` | Metrics and one script per experiment; results in `experiments/results/` |
| `simlab/` | Simulated-student lab used to compare schedulers with known truth |
| `models/offsets.py`, `models/links.py`, `scheduler/replay.py` | Hierarchical offsets (Experiment 4), concept-link feature (Experiment 9) and replay checks (Experiment 6) |
| `artifacts/` | Fitted parameters used by the app, the six ready-made topics and their question banks |
| `eval_dashboard/` | Streamlit dashboard: pilot monitor, Remem Test switch, findings and experiment results |
| `deploy/`, `docs/DEPLOY.md` | Server setup (systemd, Caddy HTTPS, nightly backup) |
| `docs/` | Specification, deployment guide, per-module viva notes |
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
python -m backend.admin_create_user create user01                  # a student; prints a generated password once
python -m backend.admin_create_user create aryan --role admin      # the owner's account (pilot view and dashboard)
python -m uvicorn backend.main:app --port 8000
```

Open http://localhost:8000. Accounts are created by the owner only (at most 15 student accounts: 10 for the study plus 5 spares). `python -m backend.admin_create_user --help` lists reset, disable and list actions.

**Reminders** are off until the server has push keys. Run `python -m backend.push keys` once and put the two printed lines (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`) and `VAPID_SUBJECT` (the site address) in `.env`. Push needs HTTPS, so test it on the deployed server.

## Run the dashboard

```powershell
streamlit run eval_dashboard/app.py
```

The Pilot page loads live data from the server with your admin account. Put `REMEM_SERVER_URL`, `REMEM_ADMIN_USER` and `REMEM_ADMIN_PASSWORD` in `.env` to connect automatically (otherwise a connect form appears). From the same page you can open or close the Remem Test (opening it asks first, because everyone with reminders on is notified) and reset test data for chosen accounts (a typed confirmation protects it). To keep dated backups on this computer, run `python -m eval_dashboard.pull_backup`, or schedule `deploy\pull_backup.cmd` with Windows Task Scheduler.

## Offline demo (no internet, no API key)

```powershell
python -m backend.seed_demo --password demo-pass
python -m uvicorn backend.main:app --port 8000
```

Sign in as `demo`. The account comes with the six ready-made topics, taken from the pre-written question bank in `artifacts/fallback/`, and a short study history, so Today opens on a daily test, with first quizzes waiting and other concepts coming up later. The demo role can also move the target on the memory curve to see how the review time changes. `--reset` rebuilds the demo data. The same bank is used automatically if the language model fails while a ready-made topic is being turned into a quiz (set `REMEM_FALLBACK=0` to turn that off).

## Deploy

See [docs/DEPLOY.md](docs/DEPLOY.md): one small always-on Linux server, HTTPS through Caddy, the app as a systemd service and a nightly database backup.

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
python -m experiments.exp9_concept_link
python -m experiments.exp7_ablations
```

Outputs are written to `experiments/results/` (tables and a figure) and appended to `experiments/results/run_log.csv`. Fitted parameters used by the app are in `artifacts/`.

## Findings so far

- BKT without forgetting beats the majority, concept-difficulty and student-accuracy baselines on a chronological held-out split.
- On EdNet, a power-law forgetting term improves calibration over a non-forgetting model, but feature-driven personalisation adds very little. The app therefore starts from a documented prior (see the specification, decision D15).
- In SimLab, threshold scheduling matches a fixed interval that was tuned with knowledge of the true memory, and needs about half the reviews of SM-2 at the same coverage. It does not show a benefit from per-student personalisation.
- Small offline gains from per-concept and per-student offsets, and a larger one from the recent-failures-on-related-concepts feature (about half of that gain is a general recent-failure signal). The forgetting term and the power-law curve matter most; single student features add almost nothing. None of these extensions is deployed.
- The live pilot (up to 10 people, about 14 days) is running. It checks whether predicted recall is calibrated on real study material and compares the three methods descriptively; ten people are too few for significance tests.

These are results on simulated learners and one public dataset; they are not evidence that the app improves learning for people.

## Data and privacy

- In every result a student is an account number such as `user01`. The intro form's name, contact, age and known topics are private to the project owner, never shared, and kept out of every result and write-up.
- Answers, response times and review history are stored to evaluate the scheduler. Reminders store the device's push address and a log of the messages sent.
- Pasted notes are sent to Google Gemini to generate questions, so students are asked not to paste personal or confidential text.
- Raw data, the database, backups, `.env` and keys are excluded from version control.
