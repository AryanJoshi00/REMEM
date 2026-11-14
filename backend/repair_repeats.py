"""Repair for the early-pilot repeat bug: the practice page used to cycle through a concept's four practice questions
without end, so one sitting could hold 16 answers to the same 4 questions, and every one of them moved the schedule
(an SM-2 concept reached a 348-day interval in a single sitting).

What this does, per account:
  1. finds every answer to a practice question that was already answered in the same sitting (answers to that concept
     with gaps under 30 minutes, the session rule of spec 7) and moves it to `repeat_answers`, so it is kept for the
     record but no model, schedule or statistic reads it;
  2. replays the remaining answers in time order through the current engine (the same code the API runs), rebuilding
     each concept's state, the account's ability and answer count, and the logged prediction columns of each answer.
The final-check answers are never moved and never change the schedule. Running it twice changes nothing the second time.

    python -m backend.repair_repeats            # dry run: prints what would change, writes nothing
    python -m backend.repair_repeats --apply    # copies the database next to itself first, then repairs it
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

from backend import config, db, engine


def find_repeats(rows) -> list[int]:
    """response_ids of repeat answers. rows: one account's practice answers (not final), in time order."""
    sitting: dict[int, tuple[int, set]] = {}            # concept -> (time of last kept answer, questions answered this sitting)
    out = []
    for r in rows:
        last = sitting.get(r["concept_id"])
        seen = last[1] if last and r["ts"] - last[0] <= config.SESSION_GAP_MS else set()
        if r["question_id"] in seen:
            out.append(r["response_id"])
            continue
        seen.add(r["question_id"])
        sitting[r["concept_id"]] = (r["ts"], seen)
    return out


def replay_user(conn, models: engine.Models, uid: int) -> dict:
    """Rebuild state, ability and logged predictions for one account from the answers left in `responses`."""
    states: dict[int, dict] = {}
    ability = config.DEFAULT_ABILITY
    rts: list[int] = []                                   # response times so far, newest last (the API takes the median of the last 50)
    n = 0
    for r in conn.execute("SELECT * FROM responses WHERE user_id=? ORDER BY ts, response_id", (uid,)).fetchall():
        if r["mode"] != "final":
            recent = [x for x in rts if x is not None][-50:]
            median_rt = float(np.median(recent)) if recent else 15000.0
            st, ability, info = engine.apply_response(models, states.get(r["concept_id"], {}), ability, r["arm"], bool(r["correct"]),
                                                      r["rt_ms"], r["ts"], median_rt_ms=median_rt)
            states[r["concept_id"]] = st
            conn.execute("UPDATE responses SET pred_R=?, elapsed_days=?, mode=?, was_due=?, stability_after=?, mastery_after=? WHERE response_id=?",
                         (info["pred_R"], info["elapsed_days"], info["mode"], None if info["was_due"] is None else int(info["was_due"]),
                          st["stability_days"], st["mastery"], r["response_id"]))
            n += 1
        rts.append(r["rt_ms"])
    conn.execute("DELETE FROM state WHERE user_id=?", (uid,))
    for cid, st in states.items():
        conn.execute("""INSERT INTO state(user_id,concept_id,mastery,n_sessions,n_responses,last_ts,stability_days,t_review_days,due_at,remem_due_at,sm2_ef,sm2_reps,sm2_interval)
                        VALUES (:u,:c,:mastery,:n_sessions,:n_responses,:last_ts,:stability_days,:t_review_days,:due_at,:remem_due_at,:sm2_ef,:sm2_reps,:sm2_interval)""",
                     {"u": uid, "c": cid, **st})
    conn.execute("UPDATE users SET ability=?, n_answers=? WHERE user_id=?", (ability, n, uid))
    return states


def repair(conn, models: engine.Models | None = None, now: int | None = None) -> list[dict]:
    """Repair every account in place (the caller commits). Returns one report row per concept that has answers."""
    models = models or engine.Models.load()
    now = now or int(time.time() * 1000)
    before = {(r["user_id"], r["concept_id"]): dict(r) for r in conn.execute("SELECT * FROM state")}
    report = []
    for u in conn.execute("SELECT user_id, username FROM users WHERE user_id IN (SELECT DISTINCT user_id FROM responses) ORDER BY user_id").fetchall():
        uid = u["user_id"]
        rows = conn.execute("SELECT response_id, concept_id, question_id, ts FROM responses WHERE user_id=? AND mode!='final' ORDER BY ts, response_id", (uid,)).fetchall()
        rep = find_repeats(rows)
        moved = {}
        for rid in rep:
            r = conn.execute("SELECT * FROM responses WHERE response_id=?", (rid,)).fetchone()
            conn.execute("""INSERT INTO repeat_answers(response_id,user_id,concept_id,question_id,idem_key,ts,correct,rt_ms,mode,arm,result_json,moved_at)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (rid, uid, r["concept_id"], r["question_id"], r["idem_key"], r["ts"], r["correct"], r["rt_ms"], r["mode"], r["arm"], r["result_json"], now))
            conn.execute("DELETE FROM responses WHERE response_id=?", (rid,))
            moved[r["concept_id"]] = moved.get(r["concept_id"], 0) + 1
        after = replay_user(conn, models, uid)
        names = {r["concept_id"]: (r["name"], r["arm"]) for r in conn.execute("SELECT concept_id, name, arm FROM concepts WHERE user_id=?", (uid,))}
        for cid in sorted(set(after) | {c for (x, c) in before if x == uid}):
            b, a = before.get((uid, cid)), after.get(cid)
            report.append({"username": u["username"], "concept": names.get(cid, ("?", "?"))[0], "arm": names.get(cid, ("?", "?"))[1],
                           "answers": a["n_responses"] if a else 0, "repeats_moved": moved.get(cid, 0),
                           "due_before": _days(b["due_at"], b["last_ts"]) if b else None, "due_after": _days(a["due_at"], a["last_ts"]) if a else None,
                           "next_review": dt.datetime.fromtimestamp(a["due_at"] / 1000).strftime("%Y-%m-%d %H:%M") if a else None})
    return report


def _days(due_ms, last_ms):
    return round((due_ms - last_ms) / config.MS_PER_DAY, 2) if due_ms and last_ms else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--apply", action="store_true", help="write the repair (after copying the database next to itself)")
    a = ap.parse_args(argv)
    if not a.db.exists():
        print("No database at", a.db, file=sys.stderr)
        return 2
    db.init_db(a.db)                                       # creates repeat_answers on an older database
    conn = db.connect(a.db)
    try:
        if a.apply:
            copy = a.db.with_name(a.db.stem + ".before-repair-" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
            with sqlite3.connect(copy) as dst:
                conn.backup(dst)
            print("Copy saved:", copy)
        conn.execute("BEGIN IMMEDIATE")
        report = repair(conn)
        total = sum(r["repeats_moved"] for r in report)
        print(f"{'account':10} {'arm':6} {'kept':>4} {'moved':>5} {'interval before':>15} {'after':>7}  next review  concept")
        for r in report:
            print(f"{r['username']:10} {r['arm']:6} {r['answers']:>4} {r['repeats_moved']:>5} {str(r['due_before']):>15} {str(r['due_after']):>7}  {r['next_review'] or '-':16} {r['concept']}")
        print(f"\n{total} repeat answers {'moved to repeat_answers' if a.apply else 'would be moved (dry run, nothing written)'}.")
        conn.commit() if a.apply else conn.rollback()
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
