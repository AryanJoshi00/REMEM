"""Owner-issued accounts, salted scrypt password hashes, hashed session tokens (spec 17.3)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict

from fastapi import Depends, Header, HTTPException

from backend import config, db

_failed: dict[str, list[float]] = defaultdict(list)


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or os.urandom(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return h, salt


def verify_password(password: str, pw_hash: bytes, salt: bytes) -> bool:
    h, _ = hash_password(password, salt)
    return hmac.compare_digest(h, pw_hash)


_DUMMY = hash_password("not-a-real-password")           # used only to make unknown usernames cost the same time as real ones


def verify_dummy(password: str) -> None:
    """Run a password check against a throw-away hash so a login for a non-existent username takes as long as a real one."""
    verify_password(password, *_DUMMY)


def purge_expired_sessions(conn) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time() * 1000),))


def revoke_user_sessions(conn, user_id: int, keep_token: str | None = None) -> None:
    """Sign a user out everywhere (optionally keeping the session that made the request)."""
    if keep_token is None:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    else:
        conn.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, _hash_token(keep_token)))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_rate_limit(username: str) -> None:
    now = time.time()
    _failed[username] = [t for t in _failed[username] if now - t < config.LOGIN_WINDOW_S]
    if len(_failed[username]) >= config.LOGIN_MAX_FAILS:
        raise HTTPException(429, "Too many failed logins. Try again later.")


def register_failure(username: str) -> None:
    _failed[username].append(time.time())


def clear_failures(username: str) -> None:
    _failed.pop(username, None)


def create_user(conn, username: str, password: str, role: str = "student") -> int:
    if role == "student":
        n = conn.execute("SELECT COUNT(*) FROM users WHERE role='student'").fetchone()[0]
        if n >= config.MAX_STUDENT_ACCOUNTS:
            raise ValueError(f"Student account cap ({config.MAX_STUDENT_ACCOUNTS}) reached")
    h, salt = hash_password(password)
    cur = conn.execute("INSERT INTO users(username,pw_hash,salt,role,ability,created_at) VALUES (?,?,?,?,?,?)",
                       (username, h, salt, role, config.DEFAULT_ABILITY, int(time.time() * 1000)))
    return cur.lastrowid


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    exp = int((time.time() + config.SESSION_TTL_HOURS * 3600) * 1000)
    conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (?,?,?)", (_hash_token(token), user_id, exp))
    return token


def user_from_token(conn, token: str):
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
        (_hash_token(token), int(time.time() * 1000))).fetchone()
    return row


def revoke_token(conn, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))


def _bearer(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Not authenticated")
    return authorization.split(" ", 1)[1].strip()


def current_user(token: str = Depends(_bearer)):
    """FastAPI dependency: returns a sqlite3.Row for the signed-in user or raises 401."""
    with db.session() as conn:
        row = user_from_token(conn, token)
    if row is None:
        raise HTTPException(401, "Invalid or expired session")
    return row


def consented_user(user=Depends(current_user)):
    if not user["consent_at"] or user["consent_version"] != config.CONSENT_VERSION:
        raise HTTPException(403, "Consent required")
    return user
