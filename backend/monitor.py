"""The owner's phone view of the pilot: who is using Remem, how regularly, and how the experiment is going.

Read-only and plain Python (the server has no pandas). The review definition is the same as the laptop dashboard's
(eval_dashboard/pilot.py): a concept's answers less than 30 minutes apart form one review test; its prediction is
REMEM's pred_R at the first answer, its score the share answered correctly in that test. First quizzes are learning,
not memory, and are left out. Only accounts with the role 'student' count in the experiment numbers.
"""
from __future__ import annotations

import json

from backend import config, daily

GAP_MS = 30 * 60 * 1000
GAP_BINS = [(0, 1), (1, 2), (2, 4), (4, 7), (7, None)]
ARMS = ["remem", "sm2", "fixed"]


def local_day(ts: int) -> int:
    return (ts + config.TZ_OFFSET_MS) // config.MS_PER_DAY


def review_tests(conn, user_ids: list[int]) -> list[dict]:
    """One row per concept per review test, for the given accounts."""
    if not user_ids:
        return []
    cut = conn.execute("SELECT value FROM settings WHERE key='whats_new_cutoff'").fetchone()
    cutoff = int(cut[0]) if cut else None
    marks = ",".join("?" * len(user_ids))
    rows = conn.execute(f"""SELECT user_id, concept_id, ts, correct, pred_R, elapsed_days, mode, arm FROM responses
                            WHERE user_id IN ({marks}) AND mode IN ('first','review')
                            ORDER BY user_id, concept_id, ts, response_id""", user_ids).fetchall()
    groups, cur, prev = [], [], None
    for r in rows:
        if prev is not None and (r["user_id"] != prev["user_id"] or r["concept_id"] != prev["concept_id"] or r["ts"] - prev["ts"] > GAP_MS):
            groups.append(cur); cur = []
        cur.append(r); prev = r
    if cur:
        groups.append(cur)
    out = []
    for g in groups:
        first = g[0]
        if first["mode"] != "review" or first["pred_R"] is None:
            continue
        if cutoff is not None and first["ts"] < cutoff:
            g = g[:1]                                      # before answers were held to the end of a test, only the first counts
        out.append({"user_id": first["user_id"], "concept_id": first["concept_id"], "arm": first["arm"], "ts": first["ts"],
                    "pred_R": first["pred_R"], "gap_days": first["elapsed_days"] or 0.0, "n": len(g), "right": sum(x["correct"] for x in g)})
    return out


def experiment(conn) -> dict:
    """The pilot's numbers: per method, and predicted against observed recall by days since the last review."""
    sids = [r[0] for r in conn.execute("SELECT user_id FROM users WHERE role='student'")]
    tests = review_tests(conn, sids)
    concepts = {a: 0 for a in ARMS}
    first = {a: [0, 0] for a in ARMS}
    if sids:
        marks = ",".join("?" * len(sids))
        for r in conn.execute(f"SELECT arm, COUNT(*) FROM concepts WHERE user_id IN ({marks}) GROUP BY arm", sids):
            concepts[r[0]] = r[1]
        for r in conn.execute(f"SELECT arm, COUNT(*), SUM(correct) FROM responses WHERE user_id IN ({marks}) AND mode='first' GROUP BY arm", sids):
            first[r[0]] = [r[1], r[2] or 0]
    arms = []
    for a in ARMS:
        x = [t for t in tests if t["arm"] == a]
        n = sum(t["n"] for t in x)
        arms.append({"arm": a, "concepts": concepts.get(a, 0), "reviews": len(x), "answers": n,
                     "accuracy": (sum(t["right"] for t in x) / n) if n else None,
                     "mean_gap_days": (sum(t["gap_days"] for t in x) / len(x)) if x else None,
                     "first_quiz_accuracy": (first[a][1] / first[a][0]) if first[a][0] else None})
    gaps = []
    for lo, hi in GAP_BINS:
        x = [t for t in tests if t["gap_days"] >= lo and (hi is None or t["gap_days"] < hi)]
        n = sum(t["n"] for t in x)
        if n:
            gaps.append({"label": f"{lo}–{hi} days" if hi else f"{lo}+ days", "reviews": len(x), "answers": n,
                         "predicted": sum(t["pred_R"] * t["n"] for t in x) / n, "observed": sum(t["right"] for t in x) / n})
    n = sum(t["n"] for t in tests)
    return {"reviews": len(tests), "answers": n, "arms": arms, "by_gap": gaps,
            "predicted": (sum(t["pred_R"] * t["n"] for t in tests) / n) if n else None,
            "observed": (sum(t["right"] for t in tests) / n) if n else None,
            "people_reviewing": len({t["user_id"] for t in tests})}


def _final(conn, uid: int) -> dict:
    from backend import main                               # late import: main imports this module's router
    st = main.remem_test_state(conn, uid)
    return {"total": st["total"], "answered": st["answered"], "right": st["right"], "finished": st["finished"]}


def person_row(conn, u, now: int) -> dict:
    """The summary line for one account."""
    uid, today = u["user_id"], local_day(now)
    p = conn.execute("SELECT full_name FROM profiles WHERE user_id=?", (uid,)).fetchone()
    notes = conn.execute("SELECT title, topic_id FROM notes WHERE user_id=? AND status='done' ORDER BY created_at", (uid,)).fetchall()
    days = sorted({local_day(r[0]) for r in conn.execute("SELECT ts FROM responses WHERE user_id=?", (uid,))})
    last = conn.execute("SELECT MAX(ts) FROM responses WHERE user_id=?", (uid,)).fetchone()[0]
    today_n = conn.execute("SELECT COUNT(*) FROM responses WHERE user_id=? AND ts>=?",
                           (uid, today * config.MS_PER_DAY - config.TZ_OFFSET_MS)).fetchone()[0]
    waiting = daily.remaining(conn, uid, now) if u["consent_at"] else 0
    status = ("never" if not days else "today" if days[-1] == today else "waiting" if waiting else "caught_up")
    return {"user_id": uid, "username": u["username"], "role": u["role"], "active": bool(u["active"]),
            "name": p["full_name"] if p else None, "signed_up": bool(u["consent_at"]),
            "topics": [n["title"].split(":")[0] for n in notes],
            "concepts": conn.execute("SELECT COUNT(*) FROM concepts WHERE user_id=?", (uid,)).fetchone()[0],
            "answers": conn.execute("SELECT COUNT(*) FROM responses WHERE user_id=?", (uid,)).fetchone()[0],
            "days_active": len(days), "last_7": [d in days for d in range(today - 6, today + 1)],
            "last_ts": last, "days_away": (today - days[-1]) if days else None, "today": today_n, "waiting": waiting,
            "reminders_on": conn.execute("SELECT COUNT(*) FROM push_subs WHERE user_id=?", (uid,)).fetchone()[0] > 0,
            "status": status, "final": _final(conn, uid)}


def overview(conn, now: int) -> dict:
    users = conn.execute("SELECT * FROM users ORDER BY user_id").fetchall()
    people = [person_row(conn, u, now) for u in users]
    st = [p for p in people if p["role"] == "student" and p["active"]]
    started = [p for p in st if p["answers"]]
    open_row = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
    return {"now": now,
            "today": {"people": sum(1 for p in st if p["today"]), "answers": sum(p["today"] for p in st),
                      "students": len(st), "started": len(started),
                      "active_3d": sum(1 for p in started if p["days_away"] is not None and p["days_away"] <= 2),
                      "waiting": sum(1 for p in st if p["waiting"] and p["status"] != "today"),
                      "reminders_on": sum(1 for p in st if p["reminders_on"]),
                      "two_topics": sum(1 for p in st if len(p["topics"]) >= 2)},
            "final": {"open": bool(open_row and open_row[0] == "1"),
                      "finished": sum(1 for p in st if p["final"]["finished"]),
                      "started": sum(1 for p in st if p["final"]["answered"] and not p["final"]["finished"]),
                      "eligible": sum(1 for p in st if p["final"]["total"])},
            "people": people, "experiment": experiment(conn)}


def person(conn, uid: int, now: int) -> dict | None:
    u = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    if u is None:
        return None
    row = person_row(conn, u, now)
    p = conn.execute("SELECT age, known_topics FROM profiles WHERE user_id=?", (uid,)).fetchone()
    today = local_day(now)
    per_day = {}
    for r in conn.execute("SELECT ts FROM responses WHERE user_id=?", (uid,)):
        per_day[local_day(r[0])] = per_day.get(local_day(r[0]), 0) + 1
    topics = []
    for n in conn.execute("SELECT note_id, title, topic_id, created_at FROM notes WHERE user_id=? ORDER BY created_at", (uid,)):
        arms = {a: 0 for a in ARMS}
        for c in conn.execute("SELECT arm, COUNT(*) FROM concepts WHERE note_id=? GROUP BY arm", (n["note_id"],)):
            arms[c[0]] = c[1]
        topics.append({"title": n["title"].split(":")[0], "own_notes": n["topic_id"] is None, "added": n["created_at"],
                       "concepts": sum(arms.values()), "arms": arms})
    names = {r[0]: r[1] for r in conn.execute("SELECT concept_id, name FROM concepts WHERE user_id=?", (uid,))}
    reviews = sorted(review_tests(conn, [uid]), key=lambda t: -t["ts"])[:15]
    rem = conn.execute("SELECT ts, detail, sent FROM reminders WHERE user_id=? ORDER BY ts DESC LIMIT 7", (uid,)).fetchall()
    return row | {
        "age": p["age"] if p else None, "known_topics": json.loads(p["known_topics"]) if p else [],
        "days": [{"day_ms": d * config.MS_PER_DAY - config.TZ_OFFSET_MS, "answers": per_day.get(d, 0)} for d in range(today - 13, today + 1)],
        "topic_list": topics,
        "reviews": [{"ts": t["ts"], "concept": names.get(t["concept_id"], "?"), "arm": t["arm"], "gap_days": t["gap_days"],
                     "predicted": t["pred_R"], "right": t["right"], "n": t["n"]} for t in reviews],
        "reminders": [{"ts": r["ts"], "template": (r["detail"] or "").split(";")[0].removeprefix("tpl:") or None, "reached": r["sent"] > 0} for r in rem],
    }


def final_questions(conn) -> list[dict]:
    """Every active student's Remem Test questions, per topic and concept, with the right answer marked."""
    out = []
    for u in conn.execute("SELECT u.user_id, u.username, p.full_name FROM users u LEFT JOIN profiles p USING(user_id) WHERE u.role='student' AND u.active=1 ORDER BY u.user_id"):
        concepts = []
        for c in conn.execute("""SELECT c.concept_id, c.name, n.title FROM concepts c LEFT JOIN notes n USING(note_id)
                                 WHERE c.user_id=? ORDER BY c.concept_id""", (u["user_id"],)):
            qs = [{"stem": q["stem"], "options": json.loads(q["options_json"]), "correct": q["correct_idx"]}
                  for q in conn.execute("SELECT stem, options_json, correct_idx FROM questions WHERE concept_id=? AND is_final_test=1 AND flagged=0 ORDER BY variant_no", (c["concept_id"],))]
            if qs:
                concepts.append({"concept": c["name"], "topic": (c["title"] or "").split(":")[0], "questions": qs})
        if concepts:
            out.append({"user_id": u["user_id"], "username": u["username"], "name": u["full_name"], "concepts": concepts})
    return out
