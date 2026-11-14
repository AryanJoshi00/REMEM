"""Review reminders over web push, plus the due count for the app-icon badge.

Rule (the same for every arm, so the comparison stays fair): every REMIND_EVERY_S the server looks at each account that
turned reminders on. If at least one studied concept is due, it is between 9 am and 9 pm India time, and the account has
not had a reminder yet today, it sends one notification: "N concepts are ready to review". So nobody gets more than
one reminder a day, and nobody gets one at night. The message carries only the count (it is encrypted end to end).

Keys: run `python -m backend.push keys` once and put the two printed lines in the server's .env.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
import time
from urllib.parse import urlparse

from backend import config, db

log = logging.getLogger("remem.push")

# Browsers hand out push addresses only on these services. Anything else is refused, so a crafted "endpoint" can never
# make the server send requests into its own network.
PUSH_HOSTS = ("fcm.googleapis.com", "android.googleapis.com", "web.push.apple.com", "updates.push.services.mozilla.com",
              "push.services.mozilla.com", "notify.windows.com")
GONE = (404, 410)                 # the push service says this subscription no longer exists
MAX_FAILS = 5


def enabled() -> bool:
    return bool(config.REMINDERS_ON and config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


def endpoint_ok(endpoint: str) -> bool:
    try:
        u = urlparse(endpoint)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme == "https" and u.port in (None, 443) and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def local_day(ts: int) -> int:
    return (ts + config.TZ_OFFSET_MS) // config.MS_PER_DAY


def local_hour(ts: int) -> int:
    return ((ts + config.TZ_OFFSET_MS) % config.MS_PER_DAY) // 3_600_000


def due_count(conn, uid: int, now: int) -> int:
    """Studied concepts whose review time has come (the same list as 'Due now' on Today)."""
    return conn.execute("""SELECT COUNT(*) FROM state s JOIN concepts c ON c.concept_id=s.concept_id
                           WHERE s.user_id=? AND s.last_ts IS NOT NULL AND s.due_at<=?""", (uid, now)).fetchone()[0]


def message(n: int) -> dict:
    body = "1 concept is ready to review. A quick quiz now keeps it fresh." if n == 1 else f"{n} concepts are ready to review. A quick quiz now keeps them fresh."
    return {"title": "Time to review", "body": body, "count": n, "url": "./#/"}


def _send_one(sub, payload: dict) -> int | None:
    """Send to one device. Returns None when delivered, else the HTTP status (0 for a network problem)."""
    from pywebpush import WebPushException, webpush                      # imported here so the app starts even without the package
    try:
        webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}, json.dumps(payload),
                vapid_private_key=config.VAPID_PRIVATE_KEY, vapid_claims={"sub": config.VAPID_SUBJECT or "mailto:remem@example.invalid"},
                ttl=12 * 3600, timeout=10)
        return None
    except WebPushException as e:
        return getattr(e.response, "status_code", 0) or 0
    except Exception:                                                     # network trouble: try again next round
        return 0


def deliver(subs, payload: dict) -> list[tuple[str, int | None]]:
    """Send to each device, with no database connection held (a slow push service must never hold up answers)."""
    return [(sub["endpoint"], _send_one(sub, payload)) for sub in subs]


def record(conn, uid: int, subs, results, payload: dict, kind: str, now: int) -> tuple[int, int]:
    """Store the outcome: reset or count failures, drop subscriptions the push service says are gone, log the attempt."""
    fails = {s["endpoint"]: s["fails"] for s in subs}
    sent = failed = 0
    codes = []
    for endpoint, code in results:
        if code is None:
            sent += 1
            conn.execute("UPDATE push_subs SET fails=0 WHERE endpoint=?", (endpoint,))
            continue
        failed += 1; codes.append(code)
        if code in GONE or fails.get(endpoint, 0) + 1 >= MAX_FAILS:
            conn.execute("DELETE FROM push_subs WHERE endpoint=?", (endpoint,))
        else:
            conn.execute("UPDATE push_subs SET fails=fails+1 WHERE endpoint=?", (endpoint,))
    conn.execute("INSERT INTO reminders(user_id,ts,n_due,kind,sent,failed,detail) VALUES (?,?,?,?,?,?,?)",
                 (uid, now, payload.get("count", 0), kind, sent, failed, ",".join(map(str, codes)) or None))
    return sent, failed


def send_to_user(uid: int, payload: dict, kind: str, now: int, path=None) -> tuple[int, int]:
    with db.session(path) as conn:
        subs = [dict(r) for r in conn.execute("SELECT * FROM push_subs WHERE user_id=?", (uid,))]
    results = deliver(subs, payload)
    with db.session(path) as conn:
        return record(conn, uid, subs, results, payload, kind, now)


def run_once(now: int | None = None, path=None) -> list[dict]:
    """One round of the reminder rule. Returns what was sent (for logs and tests)."""
    now = now or int(time.time() * 1000)
    if not enabled() or not (config.REMIND_FROM_HOUR <= local_hour(now) < config.REMIND_UNTIL_HOUR):
        return []
    todo = []
    with db.session(path) as conn:                                        # 1. decide who gets one (short read)
        for (uid,) in conn.execute("SELECT DISTINCT p.user_id FROM push_subs p JOIN users u USING(user_id) WHERE u.active=1").fetchall():
            last = conn.execute("SELECT MAX(ts) FROM reminders WHERE user_id=? AND kind='due' AND sent>0", (uid,)).fetchone()[0]
            if last is not None and local_day(last) == local_day(now):
                continue                                                  # already reminded today
            n = due_count(conn, uid, now)
            if n:
                todo.append((uid, n, [dict(r) for r in conn.execute("SELECT * FROM push_subs WHERE user_id=?", (uid,))]))
    out = []
    for uid, n, subs in todo:                                             # 2. send, no lock held; 3. record
        payload = message(n)
        results = deliver(subs, payload)
        with db.session(path) as conn:
            sent, failed = record(conn, uid, subs, results, payload, "due", now)
        out.append({"user_id": uid, "n_due": n, "sent": sent, "failed": failed})
    return out


async def loop() -> None:
    """Runs inside the API process. A failing round is logged and the next one runs as usual; it never stops the app."""
    while True:
        try:
            for r in await asyncio.to_thread(run_once):
                log.info("reminder user=%s due=%s sent=%s failed=%s", r["user_id"], r["n_due"], r["sent"], r["failed"])
        except Exception:
            log.exception("reminder round failed")
        await asyncio.sleep(config.REMIND_EVERY_S)


def make_keys() -> tuple[str, str]:
    """A new VAPID key pair as (public, private), both base64url without padding."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    k = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64(pub), b64(k.private_numbers().private_value.to_bytes(32, "big"))


if __name__ == "__main__":
    if sys.argv[1:] == ["keys"]:
        pub, priv = make_keys()
        print(f"VAPID_PUBLIC_KEY={pub}\nVAPID_PRIVATE_KEY={priv}")
    else:
        print(__doc__)
