"""Append one row per experiment run to experiments/results/run_log.csv (spec 15.3)."""
from __future__ import annotations

import csv
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "experiments" / "results" / "run_log.csv"
FIELDS = ["timestamp", "experiment", "dataset", "n_students", "seed", "git_commit", "seconds", "hardware", "config", "metrics", "result_path"]


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def log_run(experiment: str, dataset: str, n_students: int, seed: int, seconds: float, config: dict, metrics: dict, result_path: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.now().isoformat(timespec="seconds"), "experiment": experiment, "dataset": dataset,
            "n_students": n_students, "seed": seed, "git_commit": git_commit(), "seconds": round(seconds, 1),
            "hardware": f"CPU {platform.processor()[:30]}, no GPU", "config": json.dumps(config), "metrics": json.dumps(metrics),
            "result_path": result_path,
        })
