"""REMEM API (spec 20). Thin routes over backend.engine / llm / auth / db. Served with the PWA from /.

Run:  python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from backend import admin, auth, config, daily, db, engine, fallback, llm, push, topics
from backend.schemas import FlagIn, LoginIn, NoteIn, PasswordIn, ProfileIn, PushEndIn, PushSubIn, RespondIn, TopicIn
from models.stability import retrievability_power
from scheduler.scheduler import t_review_days

ARMS = ["remem", "sm2", "fixed"]
_models: engine.Models | None = None


def now_ms() -> int:           # replaced in tests
    return int(time.time() * 1000)


def get_models() -> engine.Models:
    global _models
    if _models is None:
        _models = engine.Models.load()
    return _models


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    get_models()
    task = None
    if push.enabled():                                   # review reminders: a light check inside this process (backend.push)
        lg = logging.getLogger("remem.push")
        if not lg.handlers:
            h = logging.StreamHandler(); h.setFormatter(logging.Formatter("%(levelname)s:     %(name)s %(message)s")); lg.addHandler(h)
        lg.setLevel(logging.INFO)
        task = asyncio.create_task(push.loop())
    yield
    if task:
        task.cancel()


_DOCS = {} if os.getenv("REMEM_DOCS") == "1" else {"docs_url": None, "redoc_url": None, "openapi_url": None}   # no public API explorer in production
app = FastAPI(title="REMEM API", lifespan=lifespan, **_DOCS)
api = FastAPI(**_DOCS)  # mounted at /api so the PWA can live at /

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; style-src-attr 'unsafe-inline'; "
                               "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
}


@app.middleware("http")
async def security_headers(request, call_next):
    resp = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        resp.headers.setdefault(k, v)
    if not request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-cache")        # app files: always check for a newer version, so an update reaches phones at once
    return resp


# ----------------------------------------------------------------------------- helpers
def rowdict(r):
    return dict(r) if r is not None else None


def day_label(ms: int, now: int) -> float:
    return round((ms - now) / config.MS_PER_DAY, 2)


def pick_arm(conn, user) -> str:
    if user["role"] != "student":
        return "remem"
    counts = {a: 0 for a in ARMS}
    for r in conn.execute("SELECT arm, COUNT(*) n FROM concepts WHERE user_id=? GROUP BY arm", (user["user_id"],)):
        counts[r["arm"]] = r["n"]
    low = min(counts.values())
    return random.choice([a for a in ARMS if counts[a] == low])


def theta_for(user, requested: float | None) -> float:
    if requested is not None and user["role"] in ("demo", "admin"):
        return min(max(requested, 0.5), 0.99)
    return config.THETA


def concept_status(models, c, st, now, theta):
    """Per-concept view used by /due and /concepts."""
    if st is None or st["last_ts"] is None:
        return {"concept_id": c["concept_id"], "name": c["name"], "new": True, "due": True, "R_now": None, "reason": "New concept - take the first quiz."}
    R = engine.current_R(models, st["stability_days"], st["last_ts"], now)
    days = (now - st["last_ts"]) / config.MS_PER_DAY
    due = now >= (st["due_at"] or 0)
    return {"concept_id": c["concept_id"], "name": c["name"], "new": False, "due": due, "R_now": round(R, 4),
            "reason": engine.explain(c["name"], R, theta, st["n_sessions"], days, st["stability_days"], short=True),
            "explanation": engine.explain(c["name"], R, theta, st["n_sessions"], days, st["stability_days"]),
            "due_in_days": day_label(st["due_at"], now), "stability_days": round(st["stability_days"], 2),
            "mastery": round(st["mastery"], 4), "last_ts": st["last_ts"], "n_responses": st["n_responses"]}


def sitting_question_ids(conn, uid: int, cid: int, now: int) -> list[int]:
    """Practice questions already answered in the current sitting (answers to this concept with gaps under 30 minutes, ending
    less than 30 minutes ago; the same rule the engine uses to count sessions). Each is asked at most once per sitting."""
    return [r["question_id"] for r in daily.sitting(conn, uid, cid, now)]


def option_order(uid: int, qid: int) -> list[int]:
    """The order one person sees a question's four options in: random, but the same every time for that person and question
    (a reload or a second device shows the same order). Position i on screen shows stored option order[i]. The stored
    question never changes, so the correct answer is no longer mostly A for anyone, and past answers keep their meaning."""
    return random.Random(f"options:{uid}:{qid}").sample(range(4), 4)


def shown(uid: int, q) -> dict:
    """The question as one person sees it: options in their order, and a flag so their answer is mapped back."""
    opts = json.loads(q["options_json"])
    return {"stem": q["stem"], "options": [opts[i] for i in option_order(uid, q["question_id"])], "shuffled": True}


def get_concept(conn, user, cid):
    c = conn.execute("SELECT * FROM concepts WHERE concept_id=? AND user_id=?", (cid, user["user_id"])).fetchone()
    if c is None:
        raise HTTPException(404, "Unknown concept")
    return c


# ----------------------------------------------------------------------------- health + auth
@api.get("/health")
def health():
    return {"status": "ok"}


@api.post("/auth/login")
def login(body: LoginIn):
    auth.check_rate_limit(body.username)
    with db.session() as conn:
        u = conn.execute("SELECT * FROM users WHERE username=? AND active=1", (body.username,)).fetchone()
        if u is None:
            auth.verify_dummy(body.password)                    # same work as a real check, so timing does not reveal which usernames exist
        ok = u is not None and auth.verify_password(body.password, u["pw_hash"], u["salt"])
        if not ok:
            auth.register_failure(body.username)
            db.audit(conn, "failed_login", u["user_id"] if u else None, ts=now_ms())
            raise HTTPException(401, "Wrong username or password")
        auth.clear_failures(body.username)
        auth.purge_expired_sessions(conn)
        token = auth.create_session(conn, u["user_id"])
        db.audit(conn, "login", u["user_id"], ts=now_ms())
        consent = bool(u["consent_at"]) and u["consent_version"] == config.CONSENT_VERSION
        return {"token": token, "role": u["role"], "username": u["username"], "consent_ok": consent,
                "profile_ok": u["role"] == "admin" or _has_profile(conn, u["user_id"])}


@api.post("/auth/logout")
def logout(token: str = Depends(auth._bearer)):
    with db.session() as conn:
        auth.revoke_token(conn, token)
    return {"ok": True}


def _has_profile(conn, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM profiles WHERE user_id=?", (user_id,)).fetchone() is not None


@api.get("/auth/profile")
def profile_form(user=Depends(auth.current_user)):
    """What the sign-up form needs: whether it is done, and the ready-made topics to tick."""
    with db.session() as conn:
        done = _has_profile(conn, user["user_id"])
    return {"done": done, "topics": [{"id": t["id"], "title": t["title"].split(":")[0], "subject": t["subject"]} for t in topics.all_topics()]}


@api.post("/auth/profile")
def save_profile(body: ProfileIn, user=Depends(auth.current_user)):
    known = sorted({k for k in body.known_topics if topics.get_topic(k)})
    with db.session() as conn:
        conn.execute("""INSERT INTO profiles(user_id,full_name,contact,age,known_topics,created_at) VALUES (?,?,?,?,?,?)
                        ON CONFLICT(user_id) DO UPDATE SET full_name=excluded.full_name, contact=excluded.contact, age=excluded.age, known_topics=excluded.known_topics""",
                     (user["user_id"], body.full_name.strip(), body.contact.strip(), body.age, json.dumps(known), now_ms()))
        db.audit(conn, "profile", user["user_id"], ts=now_ms())
    return {"ok": True}


@api.post("/auth/consent")
def consent(user=Depends(auth.current_user)):
    with db.session() as conn:
        if user["role"] != "admin" and not _has_profile(conn, user["user_id"]):
            raise HTTPException(400, "Please fill in the short form first")
        conn.execute("UPDATE users SET consent_at=?, consent_version=? WHERE user_id=?", (now_ms(), config.CONSENT_VERSION, user["user_id"]))
        db.audit(conn, "consent", user["user_id"], config.CONSENT_VERSION, ts=now_ms())
    return {"ok": True}


@api.post("/auth/password")
def change_password(body: PasswordIn, user=Depends(auth.current_user), token: str = Depends(auth._bearer)):
    if not auth.verify_password(body.old_password, user["pw_hash"], user["salt"]):
        raise HTTPException(401, "Wrong current password")
    h, salt = auth.hash_password(body.new_password)
    with db.session() as conn:
        conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE user_id=?", (h, salt, user["user_id"]))
        auth.revoke_user_sessions(conn, user["user_id"], keep_token=token)      # every other signed-in device must sign in again
        db.audit(conn, "password_change", user["user_id"], ts=now_ms())
    return {"ok": True}


# ----------------------------------------------------------------------------- notes
def run_generation(note_id: int) -> None:
    with db.session() as conn:                       # short read; the slow LLM calls below run with no database lock held
        note = conn.execute("SELECT * FROM notes WHERE note_id=?", (note_id,)).fetchone()
        user = conn.execute("SELECT * FROM users WHERE user_id=?", (note["user_id"],)).fetchone()
    try:
        concepts = llm.generate_for_note(note["text"])
    except Exception as e:                            # message is key-free by construction
        concepts = fallback.concepts_for(note["topic_id"]) if config.USE_FALLBACK_BANK else None     # ready-made topics only
        if not concepts:
            with db.session() as conn:
                conn.execute("UPDATE notes SET status='failed', error=? WHERE note_id=?", (str(e)[:300], note_id))
            return
    with db.session() as conn:
        ts = now_ms()
        for c in concepts:
            arm = pick_arm(conn, user)
            cid = conn.execute("INSERT INTO concepts(user_id,note_id,name,source_span,arm,created_at) VALUES (?,?,?,?,?,?)",
                               (user["user_id"], note_id, c.name, c.source_span, arm, ts)).lastrowid
            for i, q in enumerate(c.questions, start=1):
                conn.execute("INSERT INTO questions(concept_id,variant_no,stem,options_json,correct_idx,is_final_test,created_at) VALUES (?,?,?,?,?,?,?)",
                             (cid, i, q.stem, json.dumps(q.options), q.correct_index, 1 if i > llm.N_PRACTICE else 0, ts))      # 4 practice, then 3 kept for the Remem Test
        conn.execute("UPDATE notes SET status='done' WHERE note_id=?", (note_id,))


def _create_note(conn, user, title: str, text: str, topic_id: str | None = None) -> int:
    ts = now_ms()
    n = conn.execute("SELECT COUNT(*) FROM notes WHERE user_id=? AND created_at>?", (user["user_id"], ts - config.MS_PER_DAY)).fetchone()[0]
    if n >= config.NOTES_PER_DAY:
        raise HTTPException(429, f"Daily note limit ({config.NOTES_PER_DAY}) reached")
    return conn.execute("INSERT INTO notes(user_id,title,text,status,created_at,topic_id) VALUES (?,?,?,?,?,?)",
                        (user["user_id"], title.strip(), text[:config.MAX_NOTE_CHARS], "pending", ts, topic_id)).lastrowid


@api.post("/notes")
def add_note(body: NoteIn, bg: BackgroundTasks, user=Depends(auth.consented_user)):
    with db.session() as conn:
        nid = _create_note(conn, user, body.title, body.text)
    bg.add_task(run_generation, nid)
    return {"note_id": nid, "status": "pending"}


def reading_state(conn, uid: int, topic_id: str, finished: bool | None = None) -> str:
    """'open' (not studied yet, or the Remem Test is finished), 'last' (one last read is still allowed) or 'locked'.
    Notes are read once: re-reading is study the model never sees, so it would blur what a review measures."""
    notes = conn.execute("SELECT last_read FROM notes WHERE user_id=? AND topic_id=? AND status!='failed'", (uid, topic_id)).fetchall()
    if not notes or (remem_test_state(conn, uid)["finished"] if finished is None else finished):
        return "open"
    return "last" if any(n["last_read"] for n in notes) else "locked"


@api.get("/topics")
def topics_list(user=Depends(auth.consented_user)):
    with db.session() as conn:
        done = {r["topic_id"] for r in conn.execute("SELECT topic_id FROM notes WHERE user_id=? AND topic_id IS NOT NULL AND status!='failed'", (user["user_id"],))}
        sug = topics.suggest(conn, user["user_id"])
        row = conn.execute("SELECT known_topics FROM profiles WHERE user_id=?", (user["user_id"],)).fetchone()
        known = set(json.loads(row["known_topics"])) if row else set()
        finished = remem_test_state(conn, user["user_id"])["finished"]
        reading = {tid: reading_state(conn, user["user_id"], tid, finished) for tid in done}
    return {"suggested": sug, "topics": [{**{k: t[k] for k in ("id", "title", "subject", "blurb", "minutes", "words")}, "done": t["id"] in done, "known": t["id"] in known,
                                          "reading": reading.get(t["id"], "open")} for t in topics.all_topics()]}


@api.get("/topics/{topic_id}")
def topic_read(topic_id: str, user=Depends(auth.consented_user)):
    """The full text of a ready-made topic, read once before the quiz. Locked after that until the Remem Test is finished;
    people who made a quiz before the lock existed get one last read, used up when they open it or start their next test."""
    t = topics.get_topic(topic_id)
    if t is None:
        raise HTTPException(404, "Unknown topic")
    with db.session() as conn:
        state = reading_state(conn, user["user_id"], topic_id)
        if state == "locked":
            raise HTTPException(403, "These notes are locked until you finish the Remem Test.")
        if state == "last":
            conn.execute("UPDATE notes SET last_read=0 WHERE user_id=? AND topic_id=?", (user["user_id"], topic_id))
        done = conn.execute("SELECT 1 FROM notes WHERE user_id=? AND topic_id=? AND status!='failed' LIMIT 1", (user["user_id"], topic_id)).fetchone() is not None
    return {**{k: t[k] for k in ("id", "title", "subject", "blurb", "minutes", "words", "text")}, "done": done, "last_read": state == "last"}


@api.post("/notes/topic")
def add_topic_note(body: TopicIn, bg: BackgroundTasks, user=Depends(auth.consented_user)):
    t = topics.get_topic(body.topic_id)
    if t is None:
        raise HTTPException(404, "Unknown topic")
    with db.session() as conn:
        nid = _create_note(conn, user, t["title"], t["text"], t["id"])
    bg.add_task(run_generation, nid)
    return {"note_id": nid, "status": "pending"}


@api.get("/notes/{note_id}")
def note_status(note_id: int, user=Depends(auth.consented_user)):
    with db.session() as conn:
        n = conn.execute("SELECT note_id,title,status,error FROM notes WHERE note_id=? AND user_id=?", (note_id, user["user_id"])).fetchone()
        if n is None:
            raise HTTPException(404, "Unknown note")
        cs = conn.execute("SELECT concept_id,name FROM concepts WHERE note_id=?", (note_id,)).fetchall()
    return {**dict(n), "concepts": [dict(c) for c in cs]}


# ----------------------------------------------------------------------------- study loop
@api.get("/due")
def due(user=Depends(auth.consented_user)):
    models, now = get_models(), now_ms()
    with db.session() as conn:
        concepts = conn.execute("SELECT * FROM concepts WHERE user_id=?", (user["user_id"],)).fetchall()
        states = {r["concept_id"]: r for r in conn.execute("SELECT * FROM state WHERE user_id=?", (user["user_id"],))}
    items = [concept_status(models, c, states.get(c["concept_id"]), now, config.THETA) for c in concepts]
    new = [i for i in items if i["new"]]
    due_now = sorted([i for i in items if not i["new"] and i["due"]], key=lambda i: i["R_now"])
    upcoming = sorted([i for i in items if not i["new"] and not i["due"]], key=lambda i: i["due_in_days"])
    uid = user["user_id"]
    with db.session() as conn:
        fin = remem_test_state(conn, uid)
        review = daily.build(conn, uid, now)
        first = []
        for n in conn.execute("""SELECT n.note_id, n.title FROM notes n WHERE n.user_id=? AND n.status='done' AND EXISTS (
                                   SELECT 1 FROM concepts c LEFT JOIN state s ON s.concept_id=c.concept_id AND s.user_id=c.user_id
                                   WHERE c.note_id=n.note_id AND (s.last_ts IS NULL OR s.last_ts > ?)) ORDER BY n.note_id""",
                              (uid, now - config.SESSION_GAP_MS)).fetchall():          # a concept never answered, or one answered in the last 30 minutes
            t = daily.build(conn, uid, now, n["note_id"])
            if t["total"] > t["answered"]:
                first.append({"note_id": n["note_id"], "title": n["title"].split(":")[0], "questions": t["total"] - t["answered"], "concepts": len(t["concepts"])})
        later = [s["due_at"] for s in states.values() if s["last_ts"] is not None and (s["due_at"] or 0) > now]
        seen = conn.execute("SELECT 1 FROM audit WHERE user_id=? AND event='whats_new_seen'", (uid,)).fetchone()
        cut = conn.execute("SELECT value FROM settings WHERE key='whats_new_cutoff'").fetchone()
        old_hand = bool(cut) and conn.execute("SELECT 1 FROM responses WHERE user_id=? AND ts<?", (uid, int(cut["value"]))).fetchone() is not None
        last_read = [{"topic_id": r["topic_id"], "title": r["title"].split(":")[0]} for r in conn.execute(
            "SELECT DISTINCT topic_id, title FROM notes WHERE user_id=? AND last_read=1 AND topic_id IS NOT NULL AND status='done'", (uid,))]
    return {"new": new, "due": due_now, "upcoming": upcoming, "theta": config.THETA,
            "test": {"questions": review["total"] - review["answered"], "answered": review["answered"], "concepts": len(review["concepts"])},
            "first": first, "studied": bool(later) or bool(review["concepts"]),
            "next_test_in_days": day_label(min(later), now) if later else None,
            "final": {k: fin[k] for k in ("open", "total", "answered", "finished")} | {"remaining": fin["total"] - fin["answered"]},
            "whats_new": old_hand and not seen and not fin["finished"], "last_read": last_read if not fin["finished"] else []}


def remem_test_state(conn, uid: int) -> dict:
    """The Remem Test (the delayed test): three unseen questions per concept, available only while the owner has opened it."""
    row = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
    is_open = bool(row) and row["value"] == "1"
    rows = conn.execute("""SELECT q.question_id, q.concept_id FROM questions q JOIN concepts c ON c.concept_id=q.concept_id
                           WHERE c.user_id=? AND q.is_final_test=1 AND q.flagged=0 ORDER BY q.question_id""", (uid,)).fetchall()
    qs = [r["question_id"] for r in rows]
    answered = {r["question_id"]: r["correct"] for r in conn.execute("SELECT question_id, correct FROM responses WHERE user_id=? AND mode='final'", (uid,))}
    done = [q for q in qs if q in answered]
    finished = (bool(done) and len(done) == len(qs)) or conn.execute(
        "SELECT 1 FROM audit WHERE user_id=? AND event='remem_test_finished'", (uid,)).fetchone() is not None
    return {"open": is_open, "total": len(qs), "answered": len(done), "right": sum(answered[q] for q in done),
            "finished": finished, "order": remem_test_order(uid, rows), "done": set(done)}


def remem_test_order(uid: int, rows) -> list[int]:
    """The Remem Test order, fixed per person: concepts spread out (never the same one twice in a row where avoidable),
    and each concept's own questions in a shuffled order."""
    by_concept: dict[int, list[int]] = {}
    for r in rows:
        by_concept.setdefault(r["concept_id"], []).append(r["question_id"])
    rng = random.Random(f"remem-test:{uid}")
    for cid in sorted(by_concept):
        rng.shuffle(by_concept[cid])
    slots = daily._order({cid: len(v) for cid, v in by_concept.items()}, f"remem-test:{uid}")
    nxt = {cid: iter(v) for cid, v in by_concept.items()}
    return [next(nxt[cid]) for cid in slots]


def final_state(conn, uid: int) -> dict:
    """Older shape kept for the API: the concepts that still have an unanswered Remem Test question."""
    st = remem_test_state(conn, uid)
    if not st["open"]:
        return {"open": False, "items": []}
    items = conn.execute("""SELECT c.concept_id, c.name FROM concepts c WHERE c.user_id=? AND EXISTS (
                              SELECT 1 FROM questions q WHERE q.concept_id=c.concept_id AND q.is_final_test=1 AND q.flagged=0
                              AND q.question_id NOT IN (SELECT question_id FROM responses WHERE user_id=? AND mode='final'))
                            ORDER BY c.concept_id""", (uid, uid)).fetchall()
    return {"open": True, "items": [dict(i) for i in items]}


@api.get("/final")
def final_check(user=Depends(auth.consented_user)):
    with db.session() as conn:
        return final_state(conn, user["user_id"])


@api.get("/final/next")
def remem_test_next(user=Depends(auth.consented_user)):
    """The next Remem Test question: every concept's three unseen questions, shuffled once per person, no concept names."""
    uid = user["user_id"]
    with db.session() as conn:
        st = remem_test_state(conn, uid)
        if not st["open"]:
            raise HTTPException(403, "The Remem Test is not open yet")
        if st["total"] == st["answered"]:
            return {"done": True, "total": st["total"], "right": st["right"]}
        qid = next(q for q in st["order"] if q not in st["done"])
        q = conn.execute("SELECT question_id, stem, options_json FROM questions WHERE question_id=?", (qid,)).fetchone()
    return {"done": False, "question_id": q["question_id"], **shown(uid, q), "position": st["answered"] + 1, "total": st["total"]}


# ----------------------------------------------------------------------------- the daily test
@api.get("/test/next")
def test_next(note: int | None = Query(default=None), user=Depends(auth.consented_user)):
    """Next question of today's test (all due concepts, mixed) or of one note's first quiz. No concept names until the end."""
    uid, now = user["user_id"], now_ms()
    with db.session() as conn:
        if note is not None and conn.execute("SELECT 1 FROM notes WHERE note_id=? AND user_id=?", (note, uid)).fetchone() is None:
            raise HTTPException(404, "Unknown note")
        t = daily.build(conn, uid, now, note)
        nxt = daily.next_question(t)
        if nxt is None:
            return {"done": True, **test_summary(conn, uid, now, t)}
        _, q = nxt
    return {"done": False, "question_id": q["question_id"], **shown(uid, q), "position": t["answered"] + 1, "total": t["total"],
            "concepts": len(t["concepts"])}


def test_summary(conn, uid: int, now: int, t: dict) -> dict:
    """End of a test: the score, then each concept by name with its answers (oldest first) and when it comes back."""
    rows = []
    for cid, v in t["concepts"].items():
        c = conn.execute("SELECT c.name, s.due_at FROM concepts c LEFT JOIN state s ON s.concept_id=c.concept_id AND s.user_id=c.user_id WHERE c.concept_id=?", (cid,)).fetchone()
        marks = [bool(r["correct"]) for r in reversed(v["run"])]
        rows.append({"name": c["name"], "marks": marks, "next_due_in_days": day_label(c["due_at"], now) if c["due_at"] else None})
    rows.sort(key=lambda r: r["next_due_in_days"] if r["next_due_in_days"] is not None else 1e9)
    missed = []
    for v in t["concepts"].values():
        for r in reversed(v["run"]):
            if r["correct"]:
                continue
            q = conn.execute("""SELECT q.stem, q.options_json, q.correct_idx, x.result_json FROM questions q
                                JOIN responses x ON x.question_id=q.question_id AND x.user_id=? AND x.ts=?
                                WHERE q.question_id=?""", (uid, r["ts"], r["question_id"])).fetchone()
            chosen = json.loads(q["result_json"] or "{}").get("chosen_index")
            missed.append({"ts": r["ts"], "stem": q["stem"], "options": json.loads(q["options_json"]), "correct_index": q["correct_idx"], "chosen_index": chosen})
    missed.sort(key=lambda m: m.pop("ts"))
    return {"total": t["answered"], "right": sum(sum(r["marks"]) for r in rows), "concepts": rows, "missed": missed}


@api.post("/whats-new/seen")
def whats_new_seen(user=Depends(auth.consented_user)):
    with db.session() as conn:
        if not conn.execute("SELECT 1 FROM audit WHERE user_id=? AND event='whats_new_seen'", (user["user_id"],)).fetchone():
            db.audit(conn, "whats_new_seen", user["user_id"], ts=now_ms())
    return {"ok": True}


@api.get("/concepts")
def concepts_list(user=Depends(auth.consented_user)):
    models, now = get_models(), now_ms()
    with db.session() as conn:
        concepts = conn.execute("SELECT * FROM concepts WHERE user_id=? ORDER BY concept_id", (user["user_id"],)).fetchall()
        states = {r["concept_id"]: r for r in conn.execute("SELECT * FROM state WHERE user_id=?", (user["user_id"],))}
    out = []
    for c in concepts:
        d = concept_status(models, c, states.get(c["concept_id"]), now, config.THETA)
        if user["role"] == "admin":
            d["arm"] = c["arm"]
        out.append(d)
    return {"concepts": out}


@api.get("/question/next")
def next_question(concept: int, final: int = 0, user=Depends(auth.consented_user)):
    with db.session() as conn:
        crow = get_concept(conn, user, concept)
        cname = crow["name"]
        trow = conn.execute("SELECT topic_id FROM notes WHERE note_id=?", (crow["note_id"],)).fetchone()
        topic_id = trow["topic_id"] if trow else None                 # lets the practice page link back to the notes for ready-made topics
        if final:
            on = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
            if not on or on["value"] != "1":
                raise HTTPException(403, "The Remem Test is not open yet")
            q = conn.execute("""SELECT q.* FROM questions q WHERE q.concept_id=? AND q.is_final_test=1 AND q.flagged=0
                                AND q.question_id NOT IN (SELECT question_id FROM responses WHERE user_id=? AND mode='final')""",
                             (concept, user["user_id"])).fetchone()
            if q is None:
                raise HTTPException(404, "No Remem Test question left for this concept")
        else:
            qs = conn.execute("""SELECT q.*, (SELECT COUNT(*) FROM responses r WHERE r.question_id=q.question_id AND r.user_id=?) used,
                                        (SELECT MAX(ts) FROM responses r WHERE r.question_id=q.question_id AND r.user_id=?) last_used
                                 FROM questions q WHERE q.concept_id=? AND q.is_final_test=0 AND q.flagged=0""",
                              (user["user_id"], user["user_id"], concept)).fetchall()
            if not qs:
                raise HTTPException(404, "No questions available for this concept")
            done = set(sitting_question_ids(conn, user["user_id"], concept, now_ms()))
            left = [r for r in qs if r["question_id"] not in done]
            if not left:                                                 # every practice question asked once: this sitting is over
                st = conn.execute("SELECT due_at FROM state WHERE user_id=? AND concept_id=?", (user["user_id"], concept)).fetchone()
                due_in = day_label(st["due_at"], now_ms()) if st and st["due_at"] else None
                return {"done": True, "concept_id": concept, "concept": cname, "topic_id": topic_id, "answered": len(done & {r["question_id"] for r in qs}),
                        "next_due_in_days": due_in}
            q = sorted(left, key=lambda r: (r["used"], r["last_used"] or 0, r["variant_no"]))[0]
            pos = {"position": len(qs) - len(left) + 1, "total": len(qs)}
    out = {"done": False, "question_id": q["question_id"], "concept_id": concept, "concept": cname, "topic_id": topic_id, "stem": q["stem"], "options": json.loads(q["options_json"])}
    return out if final else {**out, **pos}


@api.post("/respond")
def respond(body: RespondIn, user=Depends(auth.consented_user)):
    models, ts = get_models(), now_ms()
    with db.session() as conn:
        # The key is stored with the user id in front, so two users can never collide (older rows hold the bare key).
        body.idem_key = f"{user['user_id']}:{body.idem_key}"
        raw_key = body.idem_key.split(":", 1)[1]
        prev = conn.execute("SELECT result_json FROM responses WHERE idem_key IN (?,?) AND user_id=?", (body.idem_key, raw_key, user["user_id"])).fetchone()
        if prev:
            return json.loads(prev["result_json"])             # idempotent replay
        q = conn.execute("""SELECT q.*, c.arm, c.name, c.source_span FROM questions q JOIN concepts c ON c.concept_id=q.concept_id
                            WHERE q.question_id=? AND c.user_id=?""", (body.question_id, user["user_id"])).fetchone()
        if q is None:
            raise HTTPException(404, "Unknown question")
        if body.shuffled:                                                   # screen position -> stored option
            body.chosen_index = option_order(user["user_id"], q["question_id"])[body.chosen_index]
        correct = body.chosen_index == q["correct_idx"]
        cid = q["concept_id"]
        if q["is_final_test"]:
            on = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
            if not on or on["value"] != "1":
                raise HTTPException(403, "The Remem Test is not open yet")
            if conn.execute("SELECT 1 FROM responses WHERE user_id=? AND question_id=? AND mode='final'", (user["user_id"], q["question_id"])).fetchone():
                raise HTTPException(409, "This Remem Test question has already been answered")
            result = {"correct": correct, "chosen_index": body.chosen_index}            # the Remem Test shows nothing until its score
            conn.execute("""INSERT INTO responses(user_id,concept_id,question_id,idem_key,ts,correct,rt_ms,mode,arm,result_json)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""", (user["user_id"], cid, q["question_id"], body.idem_key, ts, int(correct), body.rt_ms, "final", q["arm"], json.dumps(result)))
            st = remem_test_state(conn, user["user_id"])
            if st["total"] and st["answered"] == st["total"] and not conn.execute(
                    "SELECT 1 FROM audit WHERE user_id=? AND event='remem_test_finished'", (user["user_id"],)).fetchone():
                db.audit(conn, "remem_test_finished", user["user_id"], ts=ts)     # stays finished even if a new topic adds questions later
            return result
        run = sitting_question_ids(conn, user["user_id"], cid, ts)
        if q["question_id"] in run:                                           # e.g. a second tab: one answer per question per sitting
            raise HTTPException(409, "You've already answered this question in this sitting.")
        due_row = conn.execute("SELECT due_at FROM state WHERE user_id=? AND concept_id=? AND last_ts IS NOT NULL", (user["user_id"], cid)).fetchone()
        if due_row and not run and (due_row["due_at"] or 0) > ts:             # no practising early: the concept's schedule decides when
            raise HTTPException(409, "This concept isn't due yet.")
        conn.execute("UPDATE notes SET last_read=0 WHERE user_id=? AND last_read=1", (user["user_id"],))   # a test has started: the one last read is gone
        st_row = conn.execute("SELECT * FROM state WHERE user_id=? AND concept_id=?", (user["user_id"], cid)).fetchone()
        st = rowdict(st_row) or {}
        meds = [r["rt_ms"] for r in conn.execute("SELECT rt_ms FROM responses WHERE user_id=? AND rt_ms IS NOT NULL ORDER BY ts DESC LIMIT 50", (user["user_id"],))]
        median_rt = float(np.median(meds)) if meds else 15000.0
        new_state, ability, info = engine.apply_response(models, st, user["ability"], q["arm"], correct, body.rt_ms, ts, median_rt_ms=median_rt)
        conn.execute("""INSERT INTO state(user_id,concept_id,mastery,n_sessions,n_responses,last_ts,stability_days,t_review_days,due_at,remem_due_at,sm2_ef,sm2_reps,sm2_interval)
                        VALUES (:u,:c,:mastery,:n_sessions,:n_responses,:last_ts,:stability_days,:t_review_days,:due_at,:remem_due_at,:sm2_ef,:sm2_reps,:sm2_interval)
                        ON CONFLICT(user_id,concept_id) DO UPDATE SET mastery=:mastery,n_sessions=:n_sessions,n_responses=:n_responses,last_ts=:last_ts,
                        stability_days=:stability_days,t_review_days=:t_review_days,due_at=:due_at,remem_due_at=:remem_due_at,sm2_ef=:sm2_ef,sm2_reps=:sm2_reps,sm2_interval=:sm2_interval""",
                     {"u": user["user_id"], "c": cid, **new_state})
        conn.execute("UPDATE users SET ability=?, n_answers=n_answers+1 WHERE user_id=?", (ability, user["user_id"]))
        days_to_next = (new_state["due_at"] - ts) / config.MS_PER_DAY
        result = {"correct": correct, "chosen_index": body.chosen_index, "mastery": round(new_state["mastery"], 4),     # the right option is shown
                  "stability_days": round(new_state["stability_days"], 2), "next_due_in_days": round(days_to_next, 2)}         # at the end of the test
        conn.execute("""INSERT INTO responses(user_id,concept_id,question_id,idem_key,ts,correct,rt_ms,pred_R,elapsed_days,mode,arm,was_due,stability_after,mastery_after,result_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (user["user_id"], cid, q["question_id"], body.idem_key, ts, int(correct), body.rt_ms, info["pred_R"], info["elapsed_days"],
                      info["mode"], q["arm"], None if info["was_due"] is None else int(info["was_due"]), new_state["stability_days"], new_state["mastery"], json.dumps(result)))
    return result


@api.get("/retention/{concept_id}")
def retention(concept_id: int, theta: float | None = Query(default=None), user=Depends(auth.consented_user)):
    models, now = get_models(), now_ms()
    th = theta_for(user, theta)
    with db.session() as conn:
        c = get_concept(conn, user, concept_id)
        st = conn.execute("SELECT * FROM state WHERE user_id=? AND concept_id=?", (user["user_id"], concept_id)).fetchone()
    if st is None or st["last_ts"] is None:
        raise HTTPException(404, "No answers yet for this concept")
    S, beta = st["stability_days"], models.stability.beta
    t_rev = t_review_days(S, beta, th, config.T_MIN_DAYS, config.T_MAX_DAYS)
    elapsed = (now - st["last_ts"]) / config.MS_PER_DAY
    next_day = (st["due_at"] - st["last_ts"]) / config.MS_PER_DAY if th == config.THETA else t_rev
    # axis fitted to the decision: about 3x the next-review interval (and always showing "now"), in whole multiples of 4 days
    horizon = float(np.clip(4 * np.ceil(max(3 * next_day, 1.2 * elapsed, 8.0) / 4), 8.0, 364.0))
    ts = np.linspace(0, horizon, 61)
    return {"concept": c["name"], "theta": th, "stability_days": round(S, 2), "elapsed_days": round(elapsed, 2),
            "R_now": round(float(retrievability_power(elapsed, S, beta)), 4),
            "model_review_day": round(t_rev, 2),
            "next_review_day": round((st["due_at"] - st["last_ts"]) / config.MS_PER_DAY, 2) if th == config.THETA else round(t_rev, 2),
            "points": [{"day": round(float(t), 2), "R": round(float(retrievability_power(t, S, beta)), 4)} for t in ts]}


@api.get("/explain/{concept_id}")
def explain_concept(concept_id: int, user=Depends(auth.consented_user)):
    models, now = get_models(), now_ms()
    with db.session() as conn:
        c = get_concept(conn, user, concept_id)
        st = conn.execute("SELECT * FROM state WHERE user_id=? AND concept_id=?", (user["user_id"], concept_id)).fetchone()
    d = concept_status(models, c, st, now, config.THETA)
    return {"explanation": d.get("explanation", d["reason"])}


@api.post("/flag")
def flag_question(body: FlagIn, user=Depends(auth.consented_user)):
    with db.session() as conn:
        q = conn.execute("SELECT q.question_id FROM questions q JOIN concepts c ON c.concept_id=q.concept_id WHERE q.question_id=? AND c.user_id=?", (body.question_id, user["user_id"])).fetchone()
        if q is None:
            raise HTTPException(404, "Unknown question")
        conn.execute("UPDATE questions SET flagged=1 WHERE question_id=?", (body.question_id,))
        db.audit(conn, "flag_question", user["user_id"], str(body.question_id), ts=now_ms())
    return {"ok": True}


# ----------------------------------------------------------------------------- reminders (web push)
@api.get("/push/key")
def push_key(user=Depends(auth.consented_user)):
    return {"enabled": push.enabled(), "public_key": config.VAPID_PUBLIC_KEY if push.enabled() else None}


@api.post("/push/subscribe")
def push_subscribe(body: PushSubIn, user=Depends(auth.consented_user)):
    if not push.enabled():
        raise HTTPException(503, "Reminders aren't switched on for this server yet.")
    if not push.endpoint_ok(body.endpoint):
        raise HTTPException(400, "This browser's push address isn't supported.")
    with db.session() as conn:                           # one phone, one account: signing in as someone else moves the phone's reminders to them
        conn.execute("""INSERT INTO push_subs(endpoint,user_id,p256dh,auth,created_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh, auth=excluded.auth, fails=0""",
                     (body.endpoint, user["user_id"], body.keys.p256dh, body.keys.auth, now_ms()))
        db.audit(conn, "push_on", user["user_id"], ts=now_ms())
    return {"ok": True}


@api.post("/push/unsubscribe")
def push_unsubscribe(body: PushEndIn, user=Depends(auth.current_user)):
    with db.session() as conn:
        n = conn.execute("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (body.endpoint, user["user_id"])).rowcount
        if n:
            db.audit(conn, "push_off", user["user_id"], ts=now_ms())
    return {"ok": True}


@api.post("/push/test")
def push_test(user=Depends(auth.consented_user)):
    """Send one sample reminder to this account's devices right away, so the person sees what it looks like."""
    if not push.enabled():
        raise HTTPException(503, "Reminders aren't switched on for this server yet.")
    now = now_ms()
    with db.session() as conn:
        last = conn.execute("SELECT MAX(ts) FROM reminders WHERE user_id=? AND kind='test'", (user["user_id"],)).fetchone()[0]
        if last and now - last < 60_000:
            raise HTTPException(429, "A test reminder was just sent. Try again in a minute.")
        if not conn.execute("SELECT 1 FROM push_subs WHERE user_id=?", (user["user_id"],)).fetchone():
            raise HTTPException(404, "Reminders aren't on for this account. Turn them on first.")
        n = push.due_count(conn, user["user_id"], now)
    payload = {"title": "Reminders are on", "body": "This is what a Remem reminder looks like. You'll get one when a concept is due to review.", "count": n, "url": "./#/"}
    sent, failed = push.send_to_user(user["user_id"], payload, "test", now)
    return {"sent": sent, "failed": failed}


api.include_router(admin.router)
app.mount("/api", api)
if config.WEBAPP.exists():
    app.mount("/", StaticFiles(directory=config.WEBAPP, html=True), name="webapp")
