"""Build the REMEM EdNet working dataset (spec §12.2-12.3).

Samples per-user KT1 files from the already-extracted archive, keeps users who are
active over several days, joins question metadata, derives correctness, maps each
question to ONE primary concept (its rarest tag), cleans and sorts.

Run from the repo root:
    python preprocessing/build_dataset.py --sample-files 20000 --target-users 4000
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
KT1_DIR = ROOT / "data" / "raw" / "EdNet-KT1" / "KT1"
QUESTIONS = ROOT / "data" / "raw" / "EdNet-content" / "contents" / "questions.csv"
OUT_DIR = ROOT / "data" / "processed"
MS_PER_DAY = 86_400_000


def load_questions() -> pd.DataFrame:
    """Question metadata with a primary concept = rarest tag (ties -> smallest id)."""
    q = pd.read_csv(QUESTIONS)
    q["tag_list"] = q["tags"].fillna("").astype(str).apply(
        lambda s: [int(x) for x in s.split(";") if x.strip() not in ("", "-1")]
    )
    freq = Counter(t for tags in q["tag_list"] for t in set(tags))

    def primary(tags: list[int]) -> float:
        if not tags:
            return np.nan
        return float(min(tags, key=lambda t: (freq[t], t)))

    q["concept_id"] = q["tag_list"].apply(primary)
    q = q.dropna(subset=["concept_id"]).copy()
    q["concept_id"] = q["concept_id"].astype(int)
    return q[["question_id", "correct_answer", "part", "concept_id"]]


def read_user(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_csv(path, usecols=["timestamp", "solving_id", "question_id", "user_answer", "elapsed_time"])
    except Exception:
        return None
    df["student_id"] = path.stem
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-files", type=int, default=20000)
    ap.add_argument("--target-users", type=int, default=4000)
    ap.add_argument("--min-span-days", type=float, default=7.0)
    ap.add_argument("--min-interactions", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="ednet_v3.parquet")
    args = ap.parse_args()

    t0 = time.time()
    files = sorted(KT1_DIR.glob("u*.csv"))
    rng = np.random.default_rng(args.seed)
    pick = rng.choice(len(files), size=min(args.sample_files, len(files)), replace=False)
    chosen = [files[i] for i in sorted(pick)]
    print(f"KT1 files available: {len(files):,}; sampling {len(chosen):,}")

    with ThreadPoolExecutor(max_workers=16) as ex:
        frames = [f for f in ex.map(read_user, chosen) if f is not None and len(f)]
    raw = pd.concat(frames, ignore_index=True)
    print(f"Read {len(raw):,} rows from {len(frames):,} users in {time.time()-t0:.0f}s")

    # --- per-user activity stats for the multi-day filter (spec §12.2) ---
    g = raw.groupby("student_id")["timestamp"]
    stats = pd.DataFrame({"n": g.size(), "span_days": (g.max() - g.min()) / MS_PER_DAY})
    stats_all = stats.copy()
    keep = stats[(stats.span_days >= args.min_span_days) & (stats.n >= args.min_interactions)]
    print(f"Users passing filter (span>={args.min_span_days}d, n>={args.min_interactions}): {len(keep):,} of {len(stats):,}")
    if len(keep) > args.target_users:
        keep = keep.sample(args.target_users, random_state=args.seed)
    df = raw[raw["student_id"].isin(keep.index)].copy()

    # --- join metadata, derive correctness, concept ---
    q = load_questions()
    df = df.merge(q, on="question_id", how="inner")
    df["correct"] = (df["user_answer"] == df["correct_answer"]).astype(np.int8)
    df = df.rename(columns={"elapsed_time": "response_time_ms"})
    n_before = len(df)
    df = df.drop_duplicates(["student_id", "question_id", "timestamp"])
    print(f"Removed {n_before-len(df):,} exact duplicate rows")
    df = df.sort_values(["student_id", "timestamp", "solving_id"], kind="mergesort").reset_index(drop=True)
    cnt = df.groupby("student_id").size()
    df = df[df["student_id"].isin(cnt[cnt >= 3].index)].reset_index(drop=True)

    df = df[["student_id", "question_id", "concept_id", "part", "timestamp", "correct", "response_time_ms"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / args.out
    df.to_parquet(out, index=False)
    stats_all.to_parquet(OUT_DIR / "ednet_v3_user_stats_all_sampled.parquet")

    meta = {
        "seed": args.seed, "sample_files": len(chosen), "users_sampled": int(len(stats_all)),
        "users_after_filter": int(df.student_id.nunique()), "rows": int(len(df)),
        "concepts": int(df.concept_id.nunique()), "questions": int(df.question_id.nunique()),
        "min_span_days": args.min_span_days, "min_interactions": args.min_interactions,
        "seconds": round(time.time() - t0, 1),
    }
    (OUT_DIR / (args.out + ".meta.json")).write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
