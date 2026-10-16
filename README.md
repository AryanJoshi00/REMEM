# REMEM --- Adaptive Learning and Revision System

REMEM is an adaptive learning project designed to help learners decide
**what to revise and when to revisit it**. It uses historical
question-answer interactions to analyze learner performance, prioritize
revision items, and present the results through an interactive
dashboard.

The project explores a learning workflow that combines
learner-performance analysis, knowledge-tracing research, and revision
scheduling. The current runnable workflow processes a subset of EdNet
KT1, calculates empirical performance for learner-question pairs,
generates a revision-priority schedule, and displays the results in
Streamlit.

## Table of Contents

-   [Project Goals](#project-goals)
-   [Features](#features)
-   [System Workflow](#system-workflow)
-   [Technology Stack](#technology-stack)
-   [Dataset](#dataset)
-   [Algorithms](#algorithms)
-   [Repository Structure](#repository-structure)
-   [Installation](#installation)
-   [Run REMEM](#run-remem)
-   [Evaluation](#evaluation)
-   [Implementation Status](#implementation-status)
-   [Limitations and Future Work](#limitations-and-future-work)

## Project Goals

REMEM aims to:

1.  Analyze historical learner responses at the question level.
2.  identify questions that may need more practice or revision.
3.  Rank revision items using learner performance and elapsed time since
    the last recorded attempt.
4.  Present revision recommendations and dataset summaries in an
    accessible dashboard.
5.  Establish a foundation for evaluating knowledge-tracing methods and
    adaptive revision strategies.

## Features

### Available in the current workflow

-   **EdNet KT1 preprocessing:** prepares a usable interaction subset
    from the EdNet dataset.
-   **Schema validation:** checks the structure of processed interaction
    and knowledge-component data.
-   **Learner-question performance analysis:** calculates empirical
    historical correctness for each learner-question pair.
-   **Revision scheduling:** creates a ranked list using a heuristic
    based on historical correctness and elapsed time.
-   **Action labels:** categorizes revision items as `Relearn`,
    `Practice`, or `Quick revision`.
-   **Interactive dashboard:** provides learner selection, revision
    tables, descriptive charts, and CSV export.
-   **Evaluation summaries:** displays descriptive statistics and
    explains the methodology and its limitations.

## System Workflow

``` text
EdNet KT1 interaction data
          |
          v
   Data preprocessing
          |
          v
 Clean interaction records ------ Question-to-knowledge-component mapping
          |
          v
 Learner-question performance estimation
          |
          v
     Revision scheduler
          |
          v
 Ranked revision schedule
          |
          v
 Streamlit dashboard and CSV export
```

A Bayesian Knowledge Tracing (BKT) experiment is also included in the
repository as a research component. Its training pipeline is not
currently completing successfully, so the active dashboard workflow uses
the empirical performance estimator and heuristic scheduler rather than
trained BKT predictions.

## Technology Stack

-   **Language:** Python
-   **Data processing:** pandas, NumPy
-   **Machine learning and experimentation:** scikit-learn, pyBKT
-   **Dashboard:** Streamlit
-   **Dataset utilities:** gdown and standard Python file-processing
    tools
-   **Development:** Visual Studio Code, Git, GitHub

See [`requirements.txt`](requirements.txt) for the project's Python
dependencies.

## Dataset

The current processed EdNet KT1 subset contains approximately:

  Measure                                      Current subset
  ------------------------------------------ ----------------
  Interaction records                                  30,811
  Learners                                                100
  Distinct questions                                    8,356
  Knowledge components in the mapping file                186

These figures describe the current local processed subset, not the
complete EdNet dataset. Raw data and generated CSV files are
intentionally excluded from version control.

### Expected processed files

The preprocessing workflow creates files under `data/processed/`,
including:

-   `ednet_clean.csv`
-   `ednet_knowledge_components.csv`
-   `ednet_question_tags.csv`
-   `ednet_sample.csv`
-   `ednet_sample_with_correct.csv`
-   `ednet_summary.csv`

The analysis scripts generate:

-   `mastery_scores.csv`
-   `revision_schedule.csv`

Generated file availability depends on which workflow steps have been
run successfully.

## Algorithms

### 1. Empirical learner-question performance

For each learner-question pair, the estimator calculates the mean of the
recorded correctness values and converts it to a percentage:

``` text
mastery_score = mean(correct) × 100
```

For example, four correct answers out of five attempts produce an
empirical historical accuracy of 80%.

This score summarizes recorded performance. It is not a calibrated
probability of latent knowledge mastery, and scores based on very few
attempts can be unstable.

### 2. Revision priority

The scheduler aggregates attempts for each learner-question pair and
combines historical performance with the time elapsed since the last
recorded attempt:

``` text
priority_score =
    (1 - mastery) × 70
    + min(days_since_review / 7, 1) × 30
```

Here, `mastery` is between 0 and 1. The historical-performance component
contributes up to 70 points, and the elapsed-time component contributes
up to 30 points.

The scheduler assigns an action based on historical accuracy:

  Historical accuracy   Suggested action
  --------------------- ------------------
  Below 50%             Relearn
  50% to below 80%      Practice
  80% or above          Quick revision

This is a heuristic scheduling rule. It has not yet been validated as a
forgetting-curve model.

### 3. Bayesian Knowledge Tracing

BKT is being explored as a method for estimating a learner's changing
knowledge state from a sequence of correct and incorrect responses. The
included BKT training experiment currently encounters a fitting error.
As a result, REMEM does not claim to generate predictions from a
successfully trained BKT model in the current workflow.

## Repository Structure

``` text
REMEM/
├── backend/                 # Backend-related project area
├── baselines/               # Baseline evaluation project area
├── configs/                 # Configuration project area
├── data/
│   ├── raw/                 # Local source datasets; not committed
│   └── processed/           # Generated data files; not committed
├── docs/                    # Project documentation
├── eval_dashboard/
│   └── app.py               # Streamlit dashboard
├── evaluation/              # Evaluation project area
├── experiments/             # Experiment project area
├── mobile/                  # Mobile application project area
├── models/
│   ├── bkt_experiment.py    # BKT training experiment
│   └── mastery_estimator.py # Empirical performance estimator
├── notebooks/               # Analysis notebooks
├── preprocessing/
│   ├── download_assistments.py
│   ├── download_ednet.py
│   └── schema_check.py
├── scheduler/
│   └── revision_scheduler.py
├── tests/                   # Test project area
├── requirements.txt
└── README.md
```

Some directories are reserved for additional project components and may
not yet contain a complete implementation.

## Installation

### Requirements

-   Python 3.13.3 was used during development.
-   Git
-   The EdNet KT1 dataset for running the full preprocessing workflow

### Windows PowerShell

Clone the repository and enter the project directory:

``` powershell
git clone https://github.com/AryanJoshi00/REMEM.git
cd REMEM
```

Create and activate a virtual environment:

``` powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Install dependencies:

``` powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks environment activation, run the following in that
terminal and retry activation:

``` powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

## Run REMEM

Run commands from the repository root with the virtual environment
activated.

### 1. Prepare the dataset

Place the EdNet KT1 archive at the location expected by
`preprocessing/download_ednet.py`. Then run:

``` powershell
python preprocessing\download_ednet.py
```

If the dataset has already been extracted and processed, do not download
or extract it again.

### 2. Validate processed schemas

``` powershell
python preprocessing\schema_check.py
```

The ASSISTments check may report a missing file if an ASSISTments
dataset has not been added. EdNet processing should be checked
separately.

### 3. Generate learner-question performance estimates

``` powershell
python models\mastery_estimator.py
```

Expected output: `data/processed/mastery_scores.csv`.

### 4. Generate a revision schedule

``` powershell
python scheduler\revision_scheduler.py
```

Expected output: `data/processed/revision_schedule.csv`.

### 5. Launch the dashboard

``` powershell
streamlit run eval_dashboard\app.py
```

Open the local address printed by Streamlit in the terminal. Select a
learner, inspect the revision table and charts, and use the dashboard's
CSV export feature.

## Evaluation

The current dashboard provides descriptive analysis of the processed
subset, including response counts, overall correctness,
revision-priority distributions, and learner-specific revision items.

These summaries help inspect the dataset and the behavior of the
heuristic. They do not establish predictive accuracy or prove that REMEM
improves learning outcomes. A rigorous evaluation should include a
held-out test set, comparison with simple baselines, suitable predictive
metrics, and learner-outcome evaluation.

## Implementation Status

The current end-to-end workflow available for demonstration is:

-   EdNet subset preprocessing
-   Schema checks for the available EdNet outputs
-   Empirical learner-question performance estimation
-   Heuristic revision scheduling
-   Streamlit dashboard with descriptive evaluation and CSV export

BKT training remains an experimental component and is not currently
working end to end. Additional directories for backend, mobile,
baselines, configuration, evaluation, experiments, and tests represent
project organization and extension points; their presence should not be
interpreted as proof that every component is complete.

## Limitations and Future Work

-   Resolve and validate the BKT fitting pipeline.
-   Build a reproducible train/test evaluation process.
-   Compare the revision heuristic against simple baselines.
-   Replace historical dataset age with current learner-specific review
    timestamps.
-   Validate revision recommendations against learning outcomes.
-   Add automated tests and configuration for repeatable runs.
-   Complete and integrate additional backend and mobile components as
    required.

## Data Handling

The EdNet dataset and generated data files are not included in the
repository. Keep raw datasets, processed CSVs, model artifacts, virtual
environments, and credentials out of version control unless their
inclusion is intentional and permitted by the relevant data terms.

------------------------------------------------------------------------

**Project:** REMEM\
**Purpose:** Adaptive learning analysis and revision planning\
**Current dashboard:** Streamlit
