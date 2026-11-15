"""Upgrade: four harder practice questions for every concept, beside the four easier ones it already has.

Concepts were made with 4 practice questions (mostly simple recall) and 3 Remem Test questions. This adds 4 harder
practice questions (level 2: a new situation, why it happens, telling it apart, working something out) to every concept
the question generator made for a ready-made topic, from artifacts/practice_hard.json. Each review then asks one easier
and one harder question per concept, so a person with one topic is not asked the same few questions again and again,
and every arm gets the same mix of difficulty. The generator's saved results are updated the same way (11 questions:
4 easier, 4 harder, 3 Remem Test), so everyone who starts these topics later gets exactly the same questions.

Existing questions and answers are not touched. A concept is only upgraded when its first practice question matches the
generator's version of that concept, so a concept made another way never gets questions written for something else.
Running it twice changes nothing the second time.

    python -m backend.practice_upgrade            # dry run on a throwaway copy: prints what would change, writes nothing
    python -m backend.practice_upgrade --apply    # copies the database next to itself first, then upgrades it
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from backend import config, db, llm, topics
from backend.remem_test_upgrade import copy_db

FIELDS = ("stem", "options", "correct_index")


def load_hard() -> dict:
    d = json.loads((config.ARTIFACTS / "practice_hard.json").read_text(encoding="utf-8"))["topics"]
    return {t: {n: [{k: q[k] for k in FIELDS} for q in qs] for n, qs in cs.items()} for t, cs in d.items()}


def generator_first_stems(conn) -> dict:
    """(topic, concept name) -> the first practice question the generator wrote for it, from its saved results."""
    out = {}
    for t in topics.all_topics():
        for chunk in llm.split_chunks(t["text"]):
            row = conn.execute("SELECT json FROM llm_cache WHERE chunk_hash=?", (llm.chunk_hash(chunk),)).fetchone()
            if row:
                for con in json.loads(row["json"])["concepts"]:
                    out[(t["id"], con["name"])] = con["questions"][0]["stem"]
    return out


def upgrade(conn, now: int | None = None) -> dict:
    now = now or int(time.time() * 1000)
    hard = load_hard()
    first = generator_first_stems(conn)
    done, skipped, same = [], [], 0
    for c in conn.execute("""SELECT c.concept_id, c.name, n.topic_id FROM concepts c LEFT JOIN notes n ON n.note_id=c.note_id
                             ORDER BY c.concept_id""").fetchall():
        key = (c["topic_id"] or "", c["name"])
        new = hard.get(key[0], {}).get(key[1])
        qs = conn.execute("SELECT variant_no, stem, level, is_final_test FROM questions WHERE concept_id=? ORDER BY variant_no", (c["concept_id"],)).fetchall()
        if not new or not qs or first.get(key) != qs[0]["stem"]:
            skipped.append((c["concept_id"], c["topic_id"], c["name"]))       # not a generator-made concept we have questions for
            continue
        if any(q["level"] == 2 for q in qs):
            same += 1
            continue
        top = max(q["variant_no"] for q in qs)
        for i, q in enumerate(new, start=1):
            conn.execute("INSERT INTO questions(concept_id,variant_no,stem,options_json,correct_idx,is_final_test,level,created_at) VALUES (?,?,?,?,?,0,2,?)",
                         (c["concept_id"], top + i, q["stem"], json.dumps(q["options"]), q["correct_index"], now))
        done.append((c["concept_id"], c["topic_id"], c["name"]))
    cache_rows = 0
    for t in topics.all_topics():
        for chunk in llm.split_chunks(t["text"]):
            h = llm.chunk_hash(chunk)
            row = conn.execute("SELECT json FROM llm_cache WHERE chunk_hash=?", (h,)).fetchone()
            if row is None:
                continue
            d = json.loads(row["json"])
            before = _names(d, chunk, llm.N_EASY + llm.N_TEST)
            changed = False
            for con in d["concepts"]:
                new = hard.get(t["id"], {}).get(con["name"])
                if new and len(con["questions"]) == llm.N_EASY + llm.N_TEST:     # 4 practice + 3 test -> 4 easier + 4 harder + 3 test
                    con["questions"] = con["questions"][:llm.N_EASY] + new + con["questions"][llm.N_EASY:]
                    changed = True
            if changed:
                after = _names(d, chunk, llm.N_VARIANTS)
                assert after == before, (t["id"], before, after)       # the same concepts come out, now with 11 questions each
                conn.execute("UPDATE llm_cache SET json=? WHERE chunk_hash=?", (json.dumps(d), h))
                cache_rows += 1
    return {"done": done, "skipped": skipped, "same": same, "cache_rows": cache_rows}


def _names(d: dict, chunk: str, n: int) -> list[str]:
    try:
        return [x.name for x in llm.validate_chunk(d, chunk, n=n)]
    except Exception:
        return []


def run(path: Path, apply: bool) -> dict:
    """Upgrade `path`. Without apply, the work is done on a throwaway copy, so the real file is not touched at all."""
    target = path
    if apply:
        copy = path.with_name(path.stem + ".before-practice-" + dt.datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
        copy_db(path, copy)                                     # the copy is taken before anything changes
        print("Copy saved:", copy)
    else:
        target = Path(tempfile.mkdtemp()) / path.name
        copy_db(path, target)
    db.init_db(target)                                          # adds the difficulty column on an older database
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
    for cid, tid, name in r["skipped"]:
        print(f"  - concept {cid:<4} {tid or '-':<20} {name}   (not one we have harder questions for: keeps its 4)")
    print(f"\n{len(r['done'])} concepts get 4 harder practice questions, {r['same']} already have them, {len(r['skipped'])} left as they are; "
          f"{r['cache_rows']} saved generator results updated." + ("" if a.apply else " Dry run, nothing written."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
