"""Review reminders (web push): the endpoint allowlist, the reminder rule, and the real encrypted send. No network."""
import base64
import os

import pytest

from backend import config, db, push
from tests.test_api import answer, client, login, make_concepts  # noqa: F401  (client is a fixture)

FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def _client_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"p256dh": b64(pub), "auth": b64(os.urandom(16))}


def _keys_on(monkeypatch):
    pub, priv = push.make_keys()
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", pub)
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", priv)
    monkeypatch.setattr(config, "REMINDERS_ON", True)
    return pub


@pytest.fixture()
def pushing(client, monkeypatch):
    _keys_on(monkeypatch)
    sent, replies = [], {}

    def fake_send(sub, payload):
        sent.append((sub["endpoint"], payload))
        return replies.get(sub["endpoint"])
    monkeypatch.setattr(push, "_send_one", fake_send)
    client.sent, client.replies = sent, replies
    return client


def _due_student(c, endpoint=FCM):
    h = login(c, "p01", "pw-for-p01!")
    cid = make_concepts(c, h)[0]["concept_id"]
    r = answer(c, h, cid, True).json()
    assert c.post("/api/push/subscribe", json={"endpoint": endpoint, "keys": _client_keys()}, headers=h).status_code == 200
    return h, r["next_due_in_days"]


def _at(day_ms: int, hour: float) -> int:
    """A time on the India-time calendar day that contains day_ms."""
    return push.local_day(day_ms) * config.MS_PER_DAY - config.TZ_OFFSET_MS + int(hour * 3_600_000)


def test_push_endpoint_allowlist():
    for ok in (FCM, "https://web.push.apple.com/QGx", "https://updates.push.services.mozilla.com/wpush/v2/x", "https://wns2-par02p.notify.windows.com/w/?token=x"):
        assert push.endpoint_ok(ok), ok
    for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://localhost:8000/api", "https://fcm.googleapis.com.evil.com/x",
                "https://evilfcm.googleapis.com.attacker.net/", "https://fcm.googleapis.com:8443/x", "file:///etc/passwd", "not a url"):
        assert not push.endpoint_ok(bad), bad


def test_subscribe_needs_keys_and_a_real_push_service(client, monkeypatch):
    monkeypatch.setattr(config, "VAPID_PUBLIC_KEY", ""); monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "")
    h = login(client, "p01", "pw-for-p01!")
    assert client.get("/api/push/key", headers=h).json() == {"enabled": False, "public_key": None}
    assert client.post("/api/push/subscribe", json={"endpoint": FCM, "keys": _client_keys()}, headers=h).status_code == 503
    pub = _keys_on(monkeypatch)
    assert client.get("/api/push/key", headers=h).json() == {"enabled": True, "public_key": pub}
    assert client.post("/api/push/subscribe", json={"endpoint": "https://127.0.0.1:8000/api/admin", "keys": _client_keys()}, headers=h).status_code == 400
    assert client.post("/api/push/subscribe", json={"endpoint": FCM, "keys": _client_keys()}, headers=h).status_code == 200
    h2 = login(client, "p02", "pw-for-p02!")                               # same phone, other account: reminders follow whoever is signed in
    assert client.post("/api/push/subscribe", json={"endpoint": FCM, "keys": _client_keys()}, headers=h2).status_code == 200
    with db.session() as conn:
        assert [tuple(r) for r in conn.execute("SELECT u.username FROM push_subs JOIN users u USING(user_id)")] == [("p02",)]
    client.post("/api/push/unsubscribe", json={"endpoint": FCM}, headers=h)   # p01 cannot remove p02's phone
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_subs").fetchone()[0] == 1
    client.post("/api/push/unsubscribe", json={"endpoint": FCM}, headers=h2)
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_subs").fetchone()[0] == 0


def test_reminder_rule_due_daytime_once_a_day(pushing):
    c = pushing
    _, gap = _due_student(c)
    assert push.run_once(c.clock["t"]) == [] and c.sent == []               # nothing due yet
    due_day = c.clock["t"] + int((gap + 1) * config.MS_PER_DAY)
    assert push.run_once(_at(due_day, 7)) == []                             # 7 am: too early
    assert push.run_once(_at(due_day, 21.02)) == []                         # just after 9 pm: too late
    out = push.run_once(_at(due_day, 9.02))                                 # just after 9 am: sent
    assert len(out) == 1 and out[0]["n_due"] == 2 and out[0]["sent"] == 1                # one due concept = one easier + one harder question
    p = c.sent[-1][1]
    assert p["count"] == 2 and p["tpl"] and "{" not in p["title"] + p["body"]               # playful copy, fully filled in
    assert push.run_once(_at(due_day, 15)) == []                            # same day: no second reminder
    assert len(push.run_once(_at(due_day + config.MS_PER_DAY, 10))) == 1    # still due the next day: one more
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reminders WHERE kind='due' AND sent=1").fetchone()[0] == 2


def test_reminder_keeps_trying_after_a_blip_and_forgets_gone_phones(pushing):
    c = pushing
    _due_student(c)
    t = _at(c.clock["t"] + 30 * config.MS_PER_DAY, 12)
    c.replies[FCM] = 503                                                    # a passing failure keeps the phone
    assert push.run_once(t)[0]["failed"] == 1
    with db.session() as conn:
        assert conn.execute("SELECT fails FROM push_subs").fetchone()[0] == 1
    assert len(push.run_once(t + 3_600_000)) == 1                           # a failed attempt does not count as reminded
    c.replies[FCM] = 410                                                    # the phone unsubscribed: forget it
    push.run_once(t + 2 * 3_600_000)
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM push_subs").fetchone()[0] == 0


def test_test_button_and_rate_limit(pushing):
    c = pushing
    h, _ = _due_student(c)
    r = c.post("/api/push/test", headers=h)
    assert r.status_code == 200 and r.json() == {"sent": 1, "failed": 0} and c.sent[-1][1]["title"] == "Reminders are on"
    assert c.post("/api/push/test", headers=h).status_code == 429
    c.clock["t"] += 61_000
    assert c.post("/api/push/test", headers=h).status_code == 200


def test_round_never_raises_when_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "VAPID_PRIVATE_KEY", "")
    assert push.run_once(client.clock["t"]) == []


def test_payload_is_encrypted_and_signed(monkeypatch):
    """The real sender: a VAPID signature and an aes128gcm body, never the text in the clear."""
    import requests
    pub = _keys_on(monkeypatch)
    monkeypatch.setattr(config, "VAPID_SUBJECT", "https://remem.example.org")
    seen = {}

    class Resp:
        def __init__(self, code):
            self.status_code, self.text, self.headers, self.reason = code, "", {}, ""

    def fake_post(url, data=None, headers=None, timeout=None, **kw):
        seen.update(url=url, data=data, headers={k.lower(): v for k, v in headers.items()})
        return Resp(seen.get("code", 201))
    monkeypatch.setattr(requests, "post", fake_post)
    sub = {"endpoint": FCM, **_client_keys()}
    assert push._send_one(sub, push.message(3)) is None
    assert seen["url"] == FCM and seen["headers"]["content-encoding"] == "aes128gcm"
    assert seen["headers"]["authorization"].startswith("vapid t=") and pub in seen["headers"]["authorization"]
    assert b"ready to review" not in seen["data"]
    seen["code"] = 410
    assert push._send_one(sub, push.message(3)) == 410


def test_nudges_situations_and_rotation():
    from backend import nudges
    base = {"n": 4, "concept": "Anchoring", "topic": "Cognitive biases", "name": "Rudra", "streak": 0, "next": 1, "away": 1}
    assert nudges.situation(base) == "normal"
    assert nudges.situation({**base, "away": 5}) == "comeback"
    assert nudges.situation({**base, "streak": 3}) == "streak"
    assert nudges.situation({**base, "n": 1}) == "one"
    assert nudges.situation({**base, "n": 20}) == "pile"
    a = nudges.pick(base, 1, 100)
    assert nudges.pick(base, 1, 100, last_id=a[0])[0] != a[0]                 # never yesterday's line twice
    assert nudges.slot(9) == "am" and nudges.slot(14) == "pm" and nudges.slot(20) == "eve"
    morning = {nudges.pick(base, u, 100, hour=10)[0] for u in range(60)}
    evening = {nudges.pick(base, u, 100, hour=19)[0] for u in range(60)}
    assert "ev1" not in morning and "am1" not in evening and "ev1" in evening   # time-of-day lines only in their slot
    ids = [t[0] for pool in nudges.T.values() for t in pool]
    assert len(ids) == len(set(ids))                                          # ids are unique (they are logged)
    for pool in nudges.T.values():                                            # every template fills in cleanly
        for t, b in (x[1:3] for x in pool):
            out = (t + b).format(**base)
            assert "{" not in out and len(t.format(**base)) <= 50 and len(b.format(**base)) <= 120


def test_remem_test_launch_and_daily_nudge(pushing):
    c = pushing
    h, _ = _due_student(c)
    from backend import auth
    with db.session() as conn:
        auth.create_user(conn, "boss", "boss-pass-12", "admin")
    ha = login(c, "boss", "boss-pass-12", consent=False)
    n0 = len(c.sent)
    assert c.post("/api/admin/final-test", json={"open": True}, headers=ha).json() == {"open": True}   # launch goes out in the background
    launch = [p for _, p in c.sent[n0:]]
    assert len(launch) == 1 and launch[0]["url"] == "./#/final" and launch[0]["tpl"].startswith("fl") and "{" not in launch[0]["title"] + launch[0]["body"]
    c.post("/api/admin/final-test", json={"open": False}, headers=ha)
    c.post("/api/admin/final-test", json={"open": True}, headers=ha)
    assert len(c.sent) == n0 + 1                                                     # told once, even if reopened
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM reminders WHERE kind='final' AND sent=1").fetchone()[0] == 1
    with db.session() as conn:                                                       # the launch went out "today" (at the app clock)
        conn.execute("UPDATE reminders SET ts=? WHERE kind='final'", (_at(c.clock["t"], 9.5),))
    assert push.run_once(_at(c.clock["t"], 11)) == []                                 # same day as the launch: no "still waiting" yet
    out = push.run_once(_at(c.clock["t"] + config.MS_PER_DAY, 10))                  # next morning: the daily reminder is about the test
    assert len(out) == 1 and c.sent[-1][1]["tpl"].startswith("fn") and c.sent[-1][1]["url"] == "./#/final"


def test_final_copy_fills_and_fits():
    from backend import nudges
    for _, t, b in (nudges.FINAL_LAUNCH, nudges.FINAL_NOT_STARTED, nudges.FINAL_LEFT, nudges.FINAL_DONE):
        tt, bb = t.format(name="Rudra", n=15, left=6, right=12), b.format(name="Rudra", n=15, left=6, right=12)
        assert "{" not in tt + bb and len(tt) <= 50 and len(bb) <= 120
    assert nudges.final_launch(None, 5, 24)["title"].startswith("Kaabil bano")
    assert nudges.final_reminder("JATIN GUPTA", 5, 3, 24, 0)["title"] == "Jatin, the Remem Test is still waiting 👀"   # not started
    assert nudges.final_reminder("JATIN GUPTA", 5, 3, 24, 10)["body"].startswith("14 Remem Test questions left")       # part-way
    assert nudges.final_done("Rudra", 12, 15)["body"].startswith("You remembered 12 of 15")


def test_mogambo_when_the_remem_test_is_finished(pushing):
    c = pushing
    h, _ = _due_student(c)
    from backend import auth
    with db.session() as conn:
        auth.create_user(conn, "boss", "boss-pass-12", "admin")
    ha = login(c, "boss", "boss-pass-12", consent=False)
    c.post("/api/admin/final-test", json={"open": True}, headers=ha)
    right = total = 0
    while True:
        q = c.get("/api/final/next", headers=h).json()
        if q["done"]:
            break
        with db.session() as conn:
            ok = conn.execute("SELECT correct_idx FROM questions WHERE question_id=?", (q["question_id"],)).fetchone()[0]
        pick = ok if total % 2 == 0 else (ok + 1) % 4                                # half right
        right += pick == ok; total += 1
        assert c.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": pick, "rt_ms": 4000, "idem_key": f"remem-test-{q['question_id']}"}, headers=h).status_code == 200
    done = [p for _, p in c.sent if p.get("tpl") == "fd1"]
    assert len(done) == 1 and done[0]["body"].startswith(f"You remembered {right} of {total}")


def test_owner_sends_messages_to_self_and_sees_reminder_words(pushing):
    c = pushing
    _due_student(c)
    from backend import auth
    with db.session() as conn:
        auth.create_user(conn, "boss", "boss-pass-12", "admin")
    ha = login(c, "boss", "boss-pass-12", consent=False)
    cat = c.get("/api/admin/notify-catalog", headers=ha).json()
    assert cat["reminders_on"] is False and len(cat["messages"]) >= 40 and all("{" not in m["title"] + m["body"] for m in cat["messages"])
    assert c.post("/api/admin/notify-self", json={"tpl": "bw1"}, headers=ha).status_code == 404            # no phone yet
    assert c.post("/api/push/subscribe", json={"endpoint": FCM + "-boss", "keys": _client_keys()}, headers=ha).status_code == 200   # the owner can turn reminders on
    r = c.post("/api/admin/notify-self", json={"tpl": "fd1", "n": 15, "right": 11}, headers=ha).json()
    assert r["sent"] == 1 and c.sent[-1][0] == FCM + "-boss" and c.sent[-1][1]["body"].startswith("You remembered 11 of 15")
    assert c.post("/api/admin/notify-self", json={"tpl": "zz9"}, headers=ha).status_code == 404
    hs = login(c, "p02", "pw-for-p02!")
    assert c.post("/api/admin/notify-self", json={"tpl": "bw1"}, headers=hs).status_code == 403            # students cannot
    assert push.run_once(_at(c.clock["t"] + 10 * config.MS_PER_DAY, 10))                                # p01 gets a daily reminder
    with db.session() as conn:
        uid = conn.execute("SELECT user_id FROM users WHERE username='p01'").fetchone()[0]
        conn.execute("INSERT INTO reminders(user_id,ts,n_due,kind,sent,failed,detail) VALUES (?,?,?,?,?,?,?)", (uid, 1, 3, "due", 1, 0, "tpl:bw2"))   # an older row: no words kept
    rems = c.get(f"/api/admin/person/{uid}", headers=ha).json()["reminders"]
    newest = [x for x in rems if x["kind"] == "due" and x["exact"]]
    assert newest and newest[0]["title"] and "{" not in newest[0]["body"]
    old = [x for x in rems if x["ts"] == 1][0]
    assert not old["exact"] and old["title"].startswith("Ghajini mat bano") and "[concept]" in old["body"]
    with db.session() as conn:                                                                       # owner messages never reach pilot numbers
        assert conn.execute("SELECT COUNT(*) FROM reminders WHERE kind='owner'").fetchone()[0] == 1
