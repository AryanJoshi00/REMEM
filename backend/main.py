"""REMEM API (spec 20). Thin routes over backend.engine / llm / auth / db. Served with the PWA from /.

Run:  python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import os
import random
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from backend import admin, auth, config, db, engine, llm, topics
from backend.schemas import FlagIn, LoginIn, NoteIn, PasswordIn, RespondIn, TopicIn
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
    yield


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
        ok = u is not None and auth.verify_password(body.password, u["pw_hash"], u["salt"])
        if not ok:
            auth.register_failure(body.username)
            db.audit(conn, "failed_login", u["user_id"] if u else None, ts=now_ms())
            raise HTTPException(401, "Wrong username or password")
        auth.clear_failures(body.username)
        token = auth.create_session(conn, u["user_id"])
        db.audit(conn, "login", u["user_id"], ts=now_ms())
        consent = bool(u["consent_at"]) and u["consent_version"] == config.CONSENT_VERSION
        return {"token": token, "role": u["role"], "username": u["username"], "consent_ok": consent}


@api.post("/auth/logout")
def logout(token: str = Depends(auth._bearer)):
    with db.session() as conn:
        auth.revoke_token(conn, token)
    return {"ok": True}


@api.post("/auth/consent")
def consent(user=Depends(auth.current_user)):
    with db.session() as conn:
        conn.execute("UPDATE users SET consent_at=?, consent_version=? WHERE user_id=?", (now_ms(), config.CONSENT_VERSION, user["user_id"]))
        db.audit(conn, "consent", user["user_id"], config.CONSENT_VERSION, ts=now_ms())
    return {"ok": True}


@api.post("/auth/password")
def change_password(body: PasswordIn, user=Depends(auth.current_user)):
    if not auth.verify_password(body.old_password, user["pw_hash"], user["salt"]):
        raise HTTPException(401, "Wrong current password")
    h, salt = auth.hash_password(body.new_password)
    with db.session() as conn:
        conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE user_id=?", (h, salt, user["user_id"]))
        db.audit(conn, "password_change", user["user_id"], ts=now_ms())
    return {"ok": True}


# ----------------------------------------------------------------------------- notes
def run_generation(note_id: int) -> None:
    with db.session() as conn:
        note = conn.execute("SELECT * FROM notes WHERE note_id=?", (note_id,)).fetchone()
        user = conn.execute("SELECT * FROM users WHERE user_id=?", (note["user_id"],)).fetchone()
        try:
            concepts = llm.generate_for_note(conn, note["text"])
        except Exception as e:            # message is key-free by construction
            conn.execute("UPDATE notes SET status='failed', error=? WHERE note_id=?", (str(e)[:300], note_id))
            return
        ts = now_ms()
        for c in concepts:
            arm = pick_arm(conn, user)
            cid = conn.execute("INSERT INTO concepts(user_id,note_id,name,source_span,arm,created_at) VALUES (?,?,?,?,?,?)",
                               (user["user_id"], note_id, c.name, c.source_span, arm, ts)).lastrowid
            for i, q in enumerate(c.questions, start=1):
                conn.execute("INSERT INTO questions(concept_id,variant_no,stem,options_json,correct_idx,is_final_test,created_at) VALUES (?,?,?,?,?,?,?)",
                             (cid, i, q.stem, json.dumps(q.options), q.correct_index, 1 if i == llm.N_VARIANTS else 0, ts))
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


@api.get("/topics")
def topics_list(user=Depends(auth.consented_user)):
    with db.session() as conn:
        done = {r["topic_id"] for r in conn.execute("SELECT topic_id FROM notes WHERE user_id=? AND topic_id IS NOT NULL AND status!='failed'", (user["user_id"],))}
        sug = topics.suggest(conn, user["user_id"])
    return {"suggested": sug, "topics": [{**{k: t[k] for k in ("id", "title", "subject", "blurb", "minutes", "words")}, "done": t["id"] in done}
                                         for t in topics.all_topics()]}


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
    with db.session() as conn:
        fin = final_state(conn, user["user_id"])
    return {"new": new, "due": due_now, "upcoming": upcoming, "theta": config.THETA, "final": {"open": fin["open"], "remaining": len(fin["items"])}}


def final_state(conn, uid: int) -> dict:
    """The delayed test: one reserved question per concept, available only while the owner has opened it."""
    row = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
    if not row or row["value"] != "1":
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
        cname = get_concept(conn, user, concept)["name"]
        if final:
            on = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
            if not on or on["value"] != "1":
                raise HTTPException(403, "The final test is not open")
            q = conn.execute("""SELECT q.* FROM questions q WHERE q.concept_id=? AND q.is_final_test=1 AND q.flagged=0
                                AND q.question_id NOT IN (SELECT question_id FROM responses WHERE user_id=? AND mode='final')""",
                             (concept, user["user_id"])).fetchone()
            if q is None:
                raise HTTPException(404, "No final-test question left for this concept")
        else:
            qs = conn.execute("""SELECT q.*, (SELECT COUNT(*) FROM responses r WHERE r.question_id=q.question_id AND r.user_id=?) used,
                                        (SELECT MAX(ts) FROM responses r WHERE r.question_id=q.question_id AND r.user_id=?) last_used
                                 FROM questions q WHERE q.concept_id=? AND q.is_final_test=0 AND q.flagged=0""",
                              (user["user_id"], user["user_id"], concept)).fetchall()
            if not qs:
                raise HTTPException(404, "No questions available for this concept")
            q = sorted(qs, key=lambda r: (r["used"], r["last_used"] or 0, r["variant_no"]))[0]
    return {"question_id": q["question_id"], "concept_id": concept, "concept": cname, "stem": q["stem"], "options": json.loads(q["options_json"])}


@api.post("/respond")
def respond(body: RespondIn, user=Depends(auth.consented_user)):
    models, ts = get_models(), now_ms()
    with db.session() as conn:
        prev = conn.execute("SELECT result_json FROM responses WHERE idem_key=? AND user_id=?", (body.idem_key, user["user_id"])).fetchone()
        if prev:
            return json.loads(prev["result_json"])             # idempotent replay
        q = conn.execute("""SELECT q.*, c.arm, c.name, c.source_span FROM questions q JOIN concepts c ON c.concept_id=q.concept_id
                            WHERE q.question_id=? AND c.user_id=?""", (body.question_id, user["user_id"])).fetchone()
        if q is None:
            raise HTTPException(404, "Unknown question")
        correct = body.chosen_index == q["correct_idx"]
        cid = q["concept_id"]
        if q["is_final_test"]:
            on = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
            if not on or on["value"] != "1":
                raise HTTPException(403, "The final test is not open")
            result = {"correct": correct, "correct_index": q["correct_idx"], "message": "Final test answer recorded."}
            conn.execute("""INSERT INTO responses(user_id,concept_id,question_id,idem_key,ts,correct,rt_ms,mode,arm,result_json)
                            VALUES (?,?,?,?,?,?,?,?,?,?)""", (user["user_id"], cid, q["question_id"], body.idem_key, ts, int(correct), body.rt_ms, "final", q["arm"], json.dumps(result)))
            return result
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
        result = {"correct": correct, "correct_index": q["correct_idx"], "mastery": round(new_state["mastery"], 4),
                  "stability_days": round(new_state["stability_days"], 2), "next_due_in_days": round(days_to_next, 2),
                  "source": q["source_span"], "message": f"Next review in about {engine.plural(days_to_next, 'day', 1) if days_to_next < 10 else engine.plural(round(days_to_next), 'day')}."}
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


api.include_router(admin.router)
app.mount("/api", api)
if config.WEBAPP.exists():
    app.mount("/", StaticFiles(directory=config.WEBAPP, html=True), name="webapp")
