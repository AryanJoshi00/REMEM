"""Upgrade: the Remem Test becomes three unseen questions per concept, written to one rubric.

Every concept already in the database was made with 5 questions (4 practice + 1 kept for the Remem Test, written by the
question generator with no particular design). This replaces that 5th question and adds a 6th and 7th, so each concept is
tested with one question of each kind: put the idea to use in a new situation, explain why, and tell it apart / put in
order / work out. The questions come from artifacts/remem_test.json (concepts the question generator made) or, for a
concept made from a fallback bank, from that bank. It also updates the generator's saved results (llm_cache) for the
ready-made topics the same way, so everyone who starts one of those topics later gets exactly the same 7 questions.

Practice questions and answers are never touched. A concept whose Remem Test has already been started is left as it is.
Running it twice changes nothing the second time.

    python -m backend.remem_test_upgrade            # dry run on a throwaway copy: prints what would change, writes nothing
    python -m backend.remem_test_upgrade --apply    # copies the database next to itself first, then upgrades it
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from backend import config, db, llm, topics

FIELDS = ("stem", "options", "correct_index")


def load_questions() -> tuple[dict, dict, dict]:
    """(written for generated concepts, from the banks, each bank concept's first question): topic id -> concept name -> ..."""
    written = {t: {n: [{k: q[k] for k in FIELDS} for q in qs] for n, qs in cs.items()}
               for t, cs in json.loads((config.ARTIFACTS / "remem_test.json").read_text(encoding="utf-8"))["topics"].items()}
    banks, bank_first = {}, {}
    for t in topics.all_topics():
        bank = json.loads((config.ARTIFACTS / "fallback" / f"{t['id']}.json").read_text(encoding="utf-8"))
        banks[t["id"]] = {c["name"]: c["questions"][llm.N_PRACTICE:llm.N_VARIANTS] for c in bank["concepts"] if len(c["questions"]) == llm.N_VARIANTS}
        bank_first[t["id"]] = {c["name"]: c["questions"][0]["stem"] for c in bank["concepts"]}
    return written, banks, bank_first


def upgrade(conn, now: int | None = None) -> dict:
    now = now or int(time.time() * 1000)
    written, banks, bank_first = load_questions()
    done, missing, started, same = [], [], [], 0
    for c in conn.execute("""SELECT c.concept_id, c.name, n.topic_id FROM concepts c LEFT JOIN notes n ON n.note_id=c.note_id
                             ORDER BY c.concept_id""").fetchall():
        qs = conn.execute("SELECT question_id, variant_no, is_final_test, stem, options_json, correct_idx FROM questions WHERE concept_id=? ORDER BY variant_no",
                          (c["concept_id"],)).fetchall()
        if [q["variant_no"] for q in qs][:llm.N_PRACTICE] != list(range(1, llm.N_PRACTICE + 1)) or any(q["is_final_test"] for q in qs[:llm.N_PRACTICE]):
            missing.append((c["concept_id"], c["topic_id"], c["name"], "unexpected question layout"))
            continue
        tid = c["topic_id"] or ""
        from_bank = bank_first.get(tid, {}).get(c["name"]) == qs[0]["stem"]   # made from the fallback bank, not by the generator
        new = banks.get(tid, {}).get(c["name"]) if from_bank else written.get(tid, {}).get(c["name"])
        if not new:
            missing.append((c["concept_id"], c["topic_id"], c["name"], "no questions written for it"))
            continue
        if conn.execute("""SELECT 1 FROM responses r JOIN questions q USING(question_id) WHERE q.concept_id=? AND q.is_final_test=1""",
                        (c["concept_id"],)).fetchone():
            started.append((c["concept_id"], c["topic_id"], c["name"]))       # never change a test someone has begun
            continue
        old = {q["variant_no"]: q for q in qs if q["variant_no"] > llm.N_PRACTICE}
        if len(old) == llm.N_TEST and all(old[llm.N_PRACTICE + i]["stem"] == q["stem"] and json.loads(old[llm.N_PRACTICE + i]["options_json"]) == q["options"]
                                          and old[llm.N_PRACTICE + i]["correct_idx"] == q["correct_index"] for i, q in enumerate(new, start=1)):
            same += 1
            continue
        for i, q in enumerate(new, start=1):
            v = llm.N_PRACTICE + i
            if v in old:
                conn.execute("UPDATE questions SET stem=?, options_json=?, correct_idx=?, is_final_test=1, flagged=0 WHERE question_id=?",
                             (q["stem"], json.dumps(q["options"]), q["correct_index"], old[v]["question_id"]))
            else:
                conn.execute("INSERT INTO questions(concept_id,variant_no,stem,options_json,correct_idx,is_final_test,created_at) VALUES (?,?,?,?,?,1,?)",
                             (c["concept_id"], v, q["stem"], json.dumps(q["options"]), q["correct_index"], now))
        done.append((c["concept_id"], c["topic_id"], c["name"]))
    cache_rows = 0
    for t in topics.all_topics():
        for chunk in llm.split_chunks(t["text"]):
            h = llm.chunk_hash(chunk)
            row = conn.execute("SELECT json FROM llm_cache WHERE chunk_hash=?", (h,)).fetchone()
            if row is None:
                continue
            d = json.loads(row["json"])
            before = [x.name for x in _validated(d, chunk)]
            changed = False
            for con in d["concepts"]:
                new = written.get(t["id"], {}).get(con["name"])
                if new and len(con["questions"]) >= llm.N_PRACTICE + 1 and con["questions"][llm.N_PRACTICE:] != new:
                    con["questions"] = con["questions"][:llm.N_PRACTICE] + new
                    changed = True
            if changed:
                after = [x.name for x in llm.validate_chunk(d, chunk)]
                assert after == before, (t["id"], before, after)    # the same concepts come out as before, now with 7 questions each
                conn.execute("UPDATE llm_cache SET json=? WHERE chunk_hash=?", (json.dumps(d), h))
                cache_rows += 1
    return {"done": done, "missing": missing, "started": started, "same": same, "cache_rows": cache_rows}


def _validated(d: dict, chunk: str):
    """The concepts that validated before the upgrade: judged on their first 5 questions, the old rule."""
    old = llm.N_VARIANTS
    try:
        llm.N_VARIANTS = llm.N_PRACTICE + 1
        return llm.validate_chunk({"concepts": [dict(c, questions=c["questions"][:llm.N_VARIANTS]) for c in d["concepts"]]}, chunk)
    finally:
        llm.N_VARIANTS = old


def copy_db(src: Path, dst: Path) -> None:
    """A consistent copy (safe while the app is running), with both files closed afterwards."""
    a, b = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        b.close(); a.close()


def run(path: Path, apply: bool) -> dict:
    """Upgrade `path`. Without apply, the work is done on a throwaway copy, so the real file is not touched at all."""
    target = path
    if not apply:
        target = Path(tempfile.mkdtemp()) / path.name
        copy_db(path, target)
    else:
        copy = path.with_name(path.stem + ".before-remem-test-" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
        copy_db(path, copy)                                                     # the copy is taken before anything changes
        print("Copy saved:", copy)
    db.init_db(target)
    conn = db.connect(target)
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = upgrade(conn)
        conn.commit()
    finally:
        conn.close()
        if not apply:
            shutil.rmtree(target.parent, ignore_errors=True)
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=config.DB_PATH)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if not a.db.exists():
        print("No database at", a.db, file=sys.stderr)
        return 2
    r = run(a.db, a.apply)
    for cid, tid, name in r["done"]:
        print(f"  + concept {cid:<4} {tid or '-':<20} {name}")
    for cid, tid, name in r["started"]:
        print(f"  = concept {cid:<4} {tid or '-':<20} {name}   (Remem Test already started: left as it is)")
    for cid, tid, name, why in r["missing"]:
        print(f"  ! concept {cid:<4} {tid or '-':<20} {name}   ({why})")
    print(f"\n{len(r['done'])} concepts get the new Remem Test, {r['same']} already have it, {len(r['started'])} already started, "
          f"{len(r['missing'])} have none; {r['cache_rows']} saved generator results updated." + ("" if a.apply else " Dry run, nothing written."))
    return 0 if not r["missing"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
