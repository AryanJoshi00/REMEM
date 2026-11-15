"""The daily test: every concept that is due, from all three arms, mixed into one test with no concept names.

A sitting of a concept is its run of answers with gaps under 30 minutes (spec 7), the same rule the engine uses to count
sessions, so each practice question is asked at most once per sitting. Two kinds of test use this:

  review  every studied concept that is due now (or already in today's sitting of a review)
  first   the new concepts of one note, right after reading it (its first quiz), kept apart from due reviews

The order is random but stable for the day (seeded), and the same concept is not asked twice in a row where avoidable.
Nothing here changes how answers are scored or scheduled: /respond does that, per concept, exactly as before.
"""
from __future__ import annotations

import random

from backend import config


def sitting(conn, uid: int, cid: int, now: int) -> list:
    """This concept's answers in the current sitting, newest first (empty when the last answer is over 30 minutes old)."""
    out, prev = [], now
    for r in conn.execute("SELECT question_id, mode, correct, ts FROM responses WHERE user_id=? AND concept_id=? AND mode!='final' ORDER BY ts DESC, response_id DESC",
                          (uid, cid)):
        if prev - r["ts"] > config.SESSION_GAP_MS:
            break
        out.append(r); prev = r["ts"]
    return out


def practice_pool(conn, uid: int, cid: int) -> list:
    """The concept's practice questions (never the Remem Test ones), least used first."""
    rows = conn.execute("""SELECT q.question_id, q.variant_no, q.stem, q.options_json, q.level,
                                  (SELECT COUNT(*) FROM responses r WHERE r.question_id=q.question_id AND r.user_id=?) used,
                                  (SELECT MAX(ts) FROM responses r WHERE r.question_id=q.question_id AND r.user_id=?) last_used
                           FROM questions q WHERE q.concept_id=? AND q.is_final_test=0 AND q.flagged=0""", (uid, uid, cid)).fetchall()
    return sorted(rows, key=lambda r: (r["used"], r["last_used"] or 0, r["variant_no"]))


FIRST_QUIZ = {1: 2, 2: 2}      # questions per concept in a topic's first quiz: two easier, two harder
REVIEW = {1: 1, 2: 1}          # and in every review after that: one easier, one harder, the same mix for every arm


def choose(pool: list, run: list, quota: dict[int, int]) -> list:
    """The questions a concept gets in this test. Those already answered in the sitting stay chosen, so the choice never
    shifts mid-test; the rest are the least recently used of each level. A level with too few questions borrows from the other."""
    by_id = {q["question_id"]: q for q in pool}
    chosen = [by_id[r["question_id"]] for r in reversed(run) if r["question_id"] in by_id]
    taken = {q["question_id"] for q in chosen}
    for level in (1, 2):
        need = quota[level] - sum(1 for q in chosen if (q["level"] or 1) == level)
        for q in pool:
            if need <= 0:
                break
            if q["question_id"] not in taken and (q["level"] or 1) == level:
                chosen.append(q); taken.add(q["question_id"]); need -= 1
    short = sum(quota.values()) - len(chosen)
    for q in pool:                                              # borrow when one level has run out
        if short <= 0:
            break
        if q["question_id"] not in taken:
            chosen.append(q); taken.add(q["question_id"]); short -= 1
    return chosen


def test_concepts(conn, uid: int, now: int, note_id: int | None = None) -> list[int]:
    """Concept ids in the review test (note_id None) or in one note's first quiz."""
    out = []
    if note_id is None:
        for s in conn.execute("SELECT concept_id, due_at FROM state WHERE user_id=? AND last_ts IS NOT NULL ORDER BY concept_id", (uid,)).fetchall():
            run = sitting(conn, uid, s["concept_id"], now)
            if run and run[-1]["mode"] == "first":
                continue                                         # still inside its first quiz: that belongs to the first-quiz test
            if run or (s["due_at"] or 0) <= now:
                out.append(s["concept_id"])
    else:
        for c in conn.execute("""SELECT c.concept_id, s.last_ts FROM concepts c LEFT JOIN state s ON s.concept_id=c.concept_id AND s.user_id=c.user_id
                                 WHERE c.user_id=? AND c.note_id=? ORDER BY c.concept_id""", (uid, note_id)).fetchall():
            run = sitting(conn, uid, c["concept_id"], now)
            if c["last_ts"] is None or (run and run[-1]["mode"] == "first"):
                out.append(c["concept_id"])
    return out


def _local_day(ts: int) -> int:
    return (ts + config.TZ_OFFSET_MS) // config.MS_PER_DAY


def _order(counts: dict[int, int], seed: str, prev=None) -> list[int]:
    """One slot per question in a random order fixed by the seed, never the same concept twice in a row unless only one
    concept is left. Each step picks at random among the other concepts, weighted by how many questions they still have;
    a concept holding more than half of what is left goes next, so the order can never paint itself into a corner."""
    rng, left, out = random.Random(seed), dict(counts), []
    while any(left.values()):
        n = sum(left.values())
        must = [c for c in sorted(left) if c != prev and left[c] * 2 > n]       # more than half of what is left: it has to go now
        pool = must or [c for c in sorted(left) if left[c] and c != prev] or [prev]
        c = rng.choices(pool, weights=[left[x] for x in pool])[0]
        out.append(c); left[c] -= 1; prev = c
    return out


def build(conn, uid: int, now: int, note_id: int | None = None) -> dict:
    """The whole test as it stands now: per concept the questions chosen for it and what is answered this sitting, and the
    order: every concept's easier question first, then the harder ones, concepts spread apart within each half."""
    concepts = {}
    for cid in test_concepts(conn, uid, now, note_id):
        pool = practice_pool(conn, uid, cid)
        if not pool:
            continue
        ids = {q["question_id"] for q in pool}
        run = [r for r in sitting(conn, uid, cid, now) if r["question_id"] in ids]
        chosen = choose(pool, run, FIRST_QUIZ if note_id is not None else REVIEW)
        concepts[cid] = {"pool": chosen, "run": run}
    seed = f"{uid}:{note_id or 'review'}:{_local_day(now)}"
    order = []
    for level in (1, 2):
        counts = {cid: sum(1 for q in v["pool"] if (q["level"] or 1) == level) for cid, v in concepts.items()}
        order += [(cid, level) for cid in _order({c: n for c, n in counts.items() if n}, f"{seed}:{level}", order[-1][0] if order else None)]
    return {"concepts": concepts, "order": order,
            "total": sum(len(v["pool"]) for v in concepts.values()), "answered": sum(len(v["run"]) for v in concepts.values())}


def next_question(t: dict):
    """(concept_id, question row) for the next question, or None when every chosen question has been answered."""
    level_of = {q["question_id"]: (q["level"] or 1) for v in t["concepts"].values() for q in v["pool"]}
    left = {}                                                   # answered so far, per concept and level: those slots are used up
    for cid, v in t["concepts"].items():
        for r in v["run"]:
            k = (cid, level_of.get(r["question_id"], 1))
            left[k] = left.get(k, 0) + 1
    for cid, level in t["order"]:
        if left.get((cid, level), 0) > 0:
            left[(cid, level)] -= 1
            continue
        done = {r["question_id"] for r in t["concepts"][cid]["run"]}
        q = next((q for q in t["concepts"][cid]["pool"] if (q["level"] or 1) == level and q["question_id"] not in done), None)
        if q is not None:
            return cid, q
    return None


def remaining(conn, uid: int, now: int, note_id: int | None = None) -> int:
    t = build(conn, uid, now, note_id)
    return t["total"] - t["answered"]
