"""API, auth, idempotency, persistence and LLM-validation tests (spec 25). The LLM is always stubbed."""
import json

import pytest
from fastapi.testclient import TestClient

from backend import auth, config, db, llm, main

NOTE = ("Photosynthesis is the process by which plants convert light energy into chemical energy stored in glucose.\n\n"
        "Chlorophyll is the green pigment in chloroplasts that absorbs light, mainly in the red and blue wavelengths.")


def fake_llm(prompt):
    qs = [{"stem": f"Question number {i} about the concept?", "options": ["alpha", "beta", "gamma", "delta"], "correct_index": i % 4} for i in range(5)]
    return json.dumps({"concepts": [
        {"name": "Photosynthesis", "source_span": "plants convert light energy into chemical energy", "questions": qs},
        {"name": "Chlorophyll", "source_span": "the green pigment in chloroplasts that absorbs light", "questions": [dict(q, stem=q["stem"] + " (chl)") for q in qs]}]})


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(llm, "_call_gemini", fake_llm)
    monkeypatch.setattr(config, "LLM_MIN_INTERVAL_S", 0)
    clock = {"t": 1_800_000_000_000}
    monkeypatch.setattr(main, "now_ms", lambda: clock["t"])
    db.init_db()
    with db.session() as conn:
        auth.create_user(conn, "p01", "pw-for-p01!", "student")
        auth.create_user(conn, "p02", "pw-for-p02!", "student")
        auth.create_user(conn, "demo", "demo-pass-1", "demo")
    c = TestClient(main.app)
    c.clock = clock
    return c


def login(c, user, pw, consent=True):
    r = c.post("/api/auth/login", json={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    if consent:
        assert c.post("/api/auth/consent", headers=h).status_code == 200
    return h


def make_concepts(c, h):
    r = c.post("/api/notes", json={"title": "Bio", "text": NOTE}, headers=h)
    assert r.status_code == 200
    s = c.get(f"/api/notes/{r.json()['note_id']}", headers=h).json()
    assert s["status"] == "done", s
    return s["concepts"]


def answer(c, h, cid, correct_wanted=True, key=None):
    q = c.get(f"/api/question/next?concept={cid}", headers=h).json()
    with db.session() as conn:
        ci = conn.execute("SELECT correct_idx FROM questions WHERE question_id=?", (q["question_id"],)).fetchone()[0]
    idx = ci if correct_wanted else (ci + 1) % 4
    return c.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": idx, "rt_ms": 8000, "idem_key": key or f"k-{q['question_id']}-{c.clock['t']}"}, headers=h)


def test_health_and_auth_required(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/due").status_code == 401
    assert client.post("/api/auth/login", json={"username": "p01", "password": "nope"}).status_code == 401


def test_password_hashed_not_plaintext(client):
    with db.session() as conn:
        row = conn.execute("SELECT pw_hash, salt FROM users WHERE username='p01'").fetchone()
    assert b"pw-for-p01" not in bytes(row["pw_hash"]) and len(row["salt"]) == 16


def test_login_rate_limit(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "p02", "password": "bad"})
    assert client.post("/api/auth/login", json={"username": "p02", "password": "pw-for-p02!"}).status_code == 429
    auth._failed.clear()


def test_consent_required_before_data(client):
    h = login(client, "p01", "pw-for-p01!", consent=False)
    assert client.get("/api/due", headers=h).status_code == 403
    assert client.post("/api/notes", json={"title": "x", "text": NOTE}, headers=h).status_code == 403


def test_notes_to_quiz_flow_and_variants(client):
    h = login(client, "p01", "pw-for-p01!")
    cs = make_concepts(client, h)
    assert len(cs) == 2
    with db.session() as conn:
        n = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        finals = conn.execute("SELECT COUNT(*) FROM questions WHERE is_final_test=1").fetchone()[0]
    assert n == 10 and finals == 2
    due = client.get("/api/due", headers=h).json()
    assert len(due["new"]) == 2 and due["due"] == []


def test_respond_updates_state_schedule_and_is_idempotent(client):
    h = login(client, "p01", "pw-for-p01!")
    cid = make_concepts(client, h)[0]["concept_id"]
    r1 = answer(client, h, cid, True, key="same-key-1")
    assert r1.status_code == 200 and r1.json()["correct"] is True and r1.json()["next_due_in_days"] > 0
    r2 = answer(client, h, cid, True, key="same-key-1")           # retried request
    assert r2.json() == r1.json()
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 1
    assert 0 < r1.json()["mastery"] < 1 and r1.json()["stability_days"] > 0


def test_due_after_time_passes_and_review_logs_prediction(client):
    h = login(client, "p01", "pw-for-p01!")
    cid = make_concepts(client, h)[0]["concept_id"]
    r = answer(client, h, cid, True)
    wait = r.json()["next_due_in_days"] + 1
    client.clock["t"] += int(wait * config.MS_PER_DAY)
    due = client.get("/api/due", headers=h).json()
    assert any(d["concept_id"] == cid for d in due["due"])
    answer(client, h, cid, True)
    with db.session() as conn:
        row = conn.execute("SELECT pred_R, elapsed_days, mode, was_due FROM responses ORDER BY response_id DESC LIMIT 1").fetchone()
    assert row["mode"] == "review" and 0 < row["pred_R"] <= 1 and row["elapsed_days"] > 0 and row["was_due"] == 1


def test_failed_answer_lowers_mastery_more_than_correct(client):
    h = login(client, "p01", "pw-for-p01!")
    a, b = [c["concept_id"] for c in make_concepts(client, h)]
    good = answer(client, h, a, True).json(); bad = answer(client, h, b, False).json()
    assert bad["mastery"] < good["mastery"]


def test_user_cannot_access_other_users_data(client):
    h1 = login(client, "p01", "pw-for-p01!"); h2 = login(client, "p02", "pw-for-p02!")
    cid = make_concepts(client, h1)[0]["concept_id"]
    assert client.get(f"/api/question/next?concept={cid}", headers=h2).status_code == 404
    assert client.get(f"/api/explain/{cid}", headers=h2).status_code == 404


def test_theta_slider_only_for_demo(client):
    hs = login(client, "p01", "pw-for-p01!"); hd = login(client, "demo", "demo-pass-1")
    cs, cd = make_concepts(client, hs)[0]["concept_id"], make_concepts(client, hd)[0]["concept_id"]
    answer(client, hs, cs, True); answer(client, hd, cd, True)
    s = client.get(f"/api/retention/{cs}?theta=0.6", headers=hs).json()
    d_lo = client.get(f"/api/retention/{cd}?theta=0.6", headers=hd).json()
    d_hi = client.get(f"/api/retention/{cd}?theta=0.95", headers=hd).json()
    assert s["theta"] == config.THETA                                  # student cannot change it
    assert d_lo["theta"] == 0.6 and d_lo["model_review_day"] > d_hi["model_review_day"]


def test_note_quota_and_flag_excludes_question(client, monkeypatch):
    monkeypatch.setattr(config, "NOTES_PER_DAY", 1)
    h = login(client, "p01", "pw-for-p01!")
    cid = make_concepts(client, h)[0]["concept_id"]
    assert client.post("/api/notes", json={"title": "again", "text": NOTE}, headers=h).status_code == 429
    q = client.get(f"/api/question/next?concept={cid}", headers=h).json()
    assert client.post("/api/flag", json={"question_id": q["question_id"]}, headers=h).status_code == 200
    seen = {client.get(f"/api/question/next?concept={cid}", headers=h).json()["question_id"] for _ in range(1)}
    assert q["question_id"] not in seen


def test_final_test_closed_by_default(client):
    h = login(client, "p01", "pw-for-p01!")
    cid = make_concepts(client, h)[0]["concept_id"]
    assert client.get(f"/api/question/next?concept={cid}&final=1", headers=h).status_code == 403


def test_state_survives_restart(client):
    h = login(client, "p01", "pw-for-p01!")
    cid = make_concepts(client, h)[0]["concept_id"]
    answer(client, h, cid, True)
    c2 = TestClient(main.app)                                          # new client, same DB file
    assert c2.get("/api/concepts", headers=h).json()["concepts"][0]["n_responses"] == 1


# ------------------------------------------------------------------ LLM validation (spec 21.2)
def _concept(**kw):
    q = [{"stem": f"Question number {i} here?", "options": ["a1", "b1", "c1", "d1"], "correct_index": 0} for i in range(5)]
    base = {"name": "Topic", "source_span": "plants convert light energy", "questions": q}
    base.update(kw)
    return {"concepts": [base]}


def test_llm_validation_rejects_bad_outputs():
    chunk = "Plants convert light energy into chemical energy."
    assert len(llm.validate_chunk(_concept(), chunk)) == 1
    assert llm.validate_chunk(_concept(source_span="this quote is not in the notes at all"), chunk) == []     # grounding
    bad_opts = _concept(); bad_opts["concepts"][0]["questions"][0]["options"] = ["x", "x", "y", "z"]
    with pytest.raises(Exception):
        llm.validate_chunk(bad_opts, chunk)                                                                    # duplicate options
    bad_idx = _concept(); bad_idx["concepts"][0]["questions"][0]["correct_index"] = 4
    with pytest.raises(Exception):
        llm.validate_chunk(bad_idx, chunk)
    few = _concept(questions=_concept()["concepts"][0]["questions"][:3])
    assert llm.validate_chunk(few, chunk) == []                                                                # too few variants


def test_llm_failure_marks_note_failed_not_crash(client, monkeypatch):
    def boom(_):
        raise RuntimeError("LLM HTTP 500")
    monkeypatch.setattr(llm, "_call_gemini", boom)
    h = login(client, "p01", "pw-for-p01!")
    r = client.post("/api/notes", json={"title": "x", "text": NOTE}, headers=h)
    s = client.get(f"/api/notes/{r.json()['note_id']}", headers=h).json()
    assert s["status"] == "failed" and "key" not in (s["error"] or "").lower()


def test_backup_is_consistent_and_rotates(client, tmp_path):
    from backend import backup_db
    h = login(client, "p01", "pw-for-p01!")
    cid = make_concepts(client, h)[0]["concept_id"]
    answer(client, h, cid, True)
    import sqlite3, time
    paths = []
    for _ in range(3):
        paths.append(backup_db.backup(tmp_path / "bk", keep=2)); time.sleep(1.1)
    assert len(list((tmp_path / "bk").glob("remem_*.db"))) == 2          # rotation keeps newest 2
    con = sqlite3.connect(paths[-1])
    assert con.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 1 and con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    con.close()


def test_topics_balanced_suggestions_and_creation(client, monkeypatch):

    def fake_topic_llm(prompt):
        chunk = prompt.split('NOTES:')[-1].split('"""')[1]
        words = chunk.split()
        qs = [{"stem": f"Question number {i} about it?", "options": ["alpha", "beta", "gamma", "delta"], "correct_index": i % 4} for i in range(5)]
        return json.dumps({"concepts": [{"name": "Idea " + words[0], "source_span": " ".join(words[:8]), "questions": qs}]})
    monkeypatch.setattr(llm, "_call_gemini", fake_topic_llm)
    ha = login(client, "p01", "pw-for-p01!")
    hb = login(client, "p02", "pw-for-p02!")
    ta = client.get("/api/topics", headers=ha).json()
    assert len(ta["topics"]) == 3 and "text" not in ta["topics"][0]
    sug_a = ta["suggested"]
    r = client.post("/api/notes/topic", json={"topic_id": sug_a}, headers=ha)
    assert r.status_code == 200
    assert client.get(f"/api/notes/{r.json()['note_id']}", headers=ha).json()["status"] == "done"
    with db.session() as conn:
        assert conn.execute("SELECT topic_id FROM notes WHERE note_id=?", (r.json()["note_id"],)).fetchone()[0] == sug_a
    # the second user is steered to a different (less chosen) topic; the first user's chosen topic is marked done
    tb = client.get("/api/topics", headers=hb).json()
    assert tb["suggested"] != sug_a
    ta2 = client.get("/api/topics", headers=ha).json()
    assert [t["done"] for t in ta2["topics"] if t["id"] == sug_a] == [True] and ta2["suggested"] != sug_a
    assert client.post("/api/notes/topic", json={"topic_id": "nope"}, headers=ha).status_code == 404


def test_old_database_gets_topic_column(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE notes (note_id INTEGER PRIMARY KEY, user_id INT, title TEXT, text TEXT, status TEXT, error TEXT, created_at INT)")
    c.commit(); c.close()
    db.init_db(p)
    assert "topic_id" in {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(notes)")}


def test_plural_and_explanations_are_plain_language():
    from backend import engine
    assert engine.plural(1, "day") == "1 day" and engine.plural(2, "day") == "2 days"
    assert engine.plural(3.0, "day", 1) == "3 days" and engine.plural(1.04, "day", 1) == "1 day" and engine.plural(2.7, "day", 1) == "2.7 days"
    for short in (True, False):
        for txt in (engine.explain("X", 1.0, 0.85, 1, 0.0, 3.0, short), engine.explain("X", 0.6, 0.85, 3, 2.5, 3.0, short)):
            assert "(s)" not in txt


def test_retention_axis_fits_next_review(client):
    h = login(client, "p01", "pw-for-p01!")
    cs = make_concepts(client, h)
    assert answer(client, h, cs[0]["concept_id"], True).status_code == 200
    r = client.get(f"/api/retention/{cs[0]['concept_id']}", headers=h).json()
    horizon = r["points"][-1]["day"]
    assert horizon % 4 == 0 and 8 <= horizon <= 364
    assert horizon >= 2.9 * r["next_review_day"] or horizon == 364      # the decision point sits well inside the plot
    assert horizon <= 3 * r["next_review_day"] + 8                     # and the axis is not stretched far beyond it


def test_security_headers_and_no_public_docs(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert client.get("/docs").status_code in (404, 405) and client.get("/openapi.json").status_code == 404
    assert client.get("/api/docs").status_code == 404 and client.get("/api/openapi.json").status_code == 404


def test_admin_snapshot_reset_final_switch_and_access(client):
    hs = login(client, "p01", "pw-for-p01!")
    with db.session() as conn:
        auth.create_user(conn, "boss", "boss-pass-12", "admin")
    ha = login(client, "boss", "boss-pass-12", consent=False)
    # students cannot use admin routes
    for path in ("/api/admin/accounts", "/api/admin/snapshot", "/api/admin/final-test"):
        assert client.get(path, headers=hs).status_code == 403
    assert client.post("/api/admin/reset", json={"confirm": "RESET", "usernames": ["p01"]}, headers=hs).status_code == 403
    cs = make_concepts(client, hs)
    assert answer(client, hs, cs[0]["concept_id"], True).status_code == 200
    accts = {a["username"]: a for a in client.get("/api/admin/accounts", headers=ha).json()["accounts"]}
    assert accts["p01"]["answers"] == 1 and accts["p01"]["concepts"] == 2
    # the snapshot is a real database without credentials
    snap = client.get("/api/admin/snapshot", headers=ha)
    assert snap.status_code == 200
    import sqlite3, tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    open(path, "wb").write(snap.content)
    c = sqlite3.connect(path)
    assert c.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert all(bytes(r[0]) == b"\x00" for r in c.execute("SELECT pw_hash FROM users"))
    c.close(); os.remove(path)
    # reset needs the phrase, an account, and leaves the account usable
    assert client.post("/api/admin/reset", json={"confirm": "yes", "usernames": ["p01"]}, headers=ha).status_code == 400
    assert client.post("/api/admin/reset", json={"confirm": "RESET", "usernames": []}, headers=ha).status_code == 400
    assert client.post("/api/admin/reset", json={"confirm": "RESET", "usernames": ["nobody"]}, headers=ha).status_code == 404
    r = client.post("/api/admin/reset", json={"confirm": "RESET", "usernames": ["p01"]}, headers=ha).json()
    assert r["answers"] == 1 and r["concepts"] == 2 and r["notes"] == 1 and r["accounts"] == 1
    assert client.get("/api/due", headers=hs).json()["new"] == []                     # still signed in and consented, but empty
    accts = {a["username"]: a for a in client.get("/api/admin/accounts", headers=ha).json()["accounts"]}
    assert accts["p01"]["answers"] == 0 and accts["p01"]["notes"] == 0 and accts["p01"]["consented"]
    # final test: closed -> open -> one question per concept -> answers recorded and not repeated
    cs = make_concepts(client, hs)
    assert client.get("/api/final", headers=hs).json() == {"open": False, "items": []}
    assert client.post("/api/admin/final-test", json={"open": True}, headers=ha).json() == {"open": True}
    fin = client.get("/api/final", headers=hs).json()
    assert fin["open"] and len(fin["items"]) == 2
    assert client.get("/api/due", headers=hs).json()["final"] == {"open": True, "remaining": 2}
    q = client.get(f"/api/question/next?concept={fin['items'][0]['concept_id']}&final=1", headers=hs).json()
    r = client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": 0, "rt_ms": 5000, "idem_key": "final-key-1"}, headers=hs)
    assert r.status_code == 200 and "correct" in r.json()
    assert len(client.get("/api/final", headers=hs).json()["items"]) == 1
    again = client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": 1, "rt_ms": 5000, "idem_key": "final-key-2"}, headers=hs)
    assert again.status_code == 409                                                   # a final question cannot be answered twice
    assert client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": 0, "rt_ms": 5000, "idem_key": "final-key-1"}, headers=hs).status_code == 200   # same key = replay
    assert client.post("/api/admin/final-test", json={"open": False}, headers=ha).json() == {"open": False}
    assert client.get(f"/api/question/next?concept={fin['items'][1]['concept_id']}&final=1", headers=hs).status_code == 403


def test_resequence_gives_admin_zero_and_keeps_data_linked(tmp_path):
    from backend import admin_create_user as acu
    p = tmp_path / "r.db"
    db.init_db(p)
    with db.session(p) as conn:
        a = auth.create_user(conn, "aryan", "x", "admin")
        u1 = auth.create_user(conn, "user02", "x", "student")
        u2 = auth.create_user(conn, "user01", "x", "student")
        conn.execute("INSERT INTO notes(user_id,title,text,status,created_at) VALUES (?,?,?,?,1)", (u1, "n", "t", "done"))
        conn.execute("INSERT INTO audit(ts,user_id,event) VALUES (1,?,'e')", (u2,))
        changed = acu.resequence(conn)
    with db.session(p) as conn:
        ids = {r["username"]: r["user_id"] for r in conn.execute("SELECT * FROM users")}
        assert ids == {"aryan": 0, "user01": 1, "user02": 2}
        assert conn.execute("SELECT user_id FROM notes").fetchone()[0] == 2        # the note followed user02
        assert conn.execute("SELECT user_id FROM audit").fetchone()[0] == 1        # and the audit row followed user01
        assert acu.resequence(conn) == []                                          # idempotent
        nid = auth.create_user(conn, "user03", "x", "student")
        assert nid == 3


def test_dashboard_server_client_end_to_end(client, tmp_path):
    from eval_dashboard.server import Server, ServerError
    hs = login(client, "p01", "pw-for-p01!")
    with db.session() as conn:
        auth.create_user(conn, "boss2", "boss-pass-22", "admin")
    srv = Server("", http=client)
    with pytest.raises(ServerError):
        srv.login("p01", "pw-for-p01!")                                    # a student is not an admin
    srv.login("boss2", "boss-pass-22")
    cs = make_concepts(client, hs)
    assert answer(client, hs, cs[0]["concept_id"], True).status_code == 200
    live = tmp_path / "pilot" / "remem_live.db"
    assert srv.download_snapshot(live) == live and live.exists() and not (live.parent / "backups").exists()   # no dated copies by default
    dated = srv.download_snapshot(live, keep_dated=2)
    assert dated.parent.name == "backups" and dated.exists()
    assert {a["username"]: a["answers"] for a in srv.accounts()}["p01"] == 1
    assert srv.set_final(True) is True and srv.final_open() is True
    r = srv.reset(["p01"])
    assert r["answers"] == 1
    with pytest.raises(ServerError):
        srv.reset(["nobody"])
