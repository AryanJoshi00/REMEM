"""Owner-only endpoints used by the admin dashboard: data snapshot, reset of test data, final-test switch.

All routes need a signed-in account whose role is `admin`. Passwords and session tokens never leave the server
(the snapshot is scrubbed), and a reset never touches accounts, passwords or roles.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from backend import auth, config, db

router = APIRouter(prefix="/admin")
RESET_PHRASE = "RESET"


def admin_user(user=Depends(auth.current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return user


def _now_ms() -> int:
    return int(time.time() * 1000)


@router.get("/accounts")
def accounts(_=Depends(admin_user)):
    """Every account with how much learning data it holds (shown in the reset dialog)."""
    with db.session() as conn:
        rows = conn.execute("""
            SELECT u.user_id, u.username, u.role, u.active, u.consent_at IS NOT NULL AS consented,
                   (SELECT COUNT(*) FROM notes n WHERE n.user_id=u.user_id) AS notes,
                   (SELECT COUNT(*) FROM concepts c WHERE c.user_id=u.user_id) AS concepts,
                   (SELECT COUNT(*) FROM responses r WHERE r.user_id=u.user_id) AS answers
            FROM users u ORDER BY u.user_id""").fetchall()
    return {"accounts": [dict(r) for r in rows]}


@router.get("/snapshot")
def snapshot(_=Depends(admin_user)):
    """A consistent copy of the database for the dashboard, with password hashes and sessions removed."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(path)
    try:
        src.backup(dst)
        dst.execute("UPDATE users SET pw_hash=x'00', salt=x'00'")
        dst.execute("DELETE FROM sessions")
        dst.commit()
    finally:
        dst.close()
        src.close()
    return FileResponse(path, media_type="application/octet-stream", filename="remem_snapshot.db",
                        background=BackgroundTask(os.remove, path))


class ResetIn(BaseModel):
    confirm: str = Field(max_length=20)
    usernames: list[str] = Field(default_factory=list, max_length=50)
    clear_consent: bool = False


@router.post("/reset")
def reset(body: ResetIn, admin=Depends(admin_user)):
    """Delete the learning data of the chosen accounts: notes, concepts, questions, answers and schedule.
    Accounts, passwords and roles stay. Irreversible, so the caller must send the confirmation phrase."""
    if body.confirm != RESET_PHRASE:
        raise HTTPException(400, f"Send confirm = \"{RESET_PHRASE}\" to proceed")
    if not body.usernames:
        raise HTTPException(400, "Choose at least one account")
    counts = {"accounts": 0, "notes": 0, "concepts": 0, "questions": 0, "answers": 0}
    with db.session() as conn:
        ids = []
        for name in body.usernames:
            row = conn.execute("SELECT user_id FROM users WHERE username=?", (name,)).fetchone()
            if row is None:
                raise HTTPException(404, f"Unknown account: {name}")
            ids.append(row["user_id"])
        for uid in ids:
            counts["answers"] += conn.execute("DELETE FROM responses WHERE user_id=?", (uid,)).rowcount
            conn.execute("DELETE FROM repeat_answers WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM state WHERE user_id=?", (uid,))
            counts["questions"] += conn.execute("DELETE FROM questions WHERE concept_id IN (SELECT concept_id FROM concepts WHERE user_id=?)", (uid,)).rowcount
            counts["concepts"] += conn.execute("DELETE FROM concepts WHERE user_id=?", (uid,)).rowcount
            counts["notes"] += conn.execute("DELETE FROM notes WHERE user_id=?", (uid,)).rowcount
            conn.execute("DELETE FROM audit WHERE user_id=?", (uid,))
            conn.execute("UPDATE users SET ability=?, n_answers=0 WHERE user_id=?", (config.DEFAULT_ABILITY, uid))
            if body.clear_consent:
                conn.execute("UPDATE users SET consent_at=NULL, consent_version=NULL WHERE user_id=?", (uid,))
            counts["accounts"] += 1
        db.audit(conn, "admin_reset", admin["user_id"], ",".join(body.usernames), ts=_now_ms())
    return {"ok": True, **counts}


class FinalIn(BaseModel):
    open: bool


@router.get("/final-test")
def final_status(_=Depends(admin_user)):
    with db.session() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
    return {"open": bool(row and row["value"] == "1")}


@router.post("/final-test")
def final_set(body: FinalIn, admin=Depends(admin_user)):
    with db.session() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES ('final_test_open',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     ("1" if body.open else "0",))
        db.audit(conn, "final_test_open" if body.open else "final_test_close", admin["user_id"], ts=_now_ms())
    return {"open": body.open}
