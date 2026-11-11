"""Fallback question bank + offline demo seed (spec 21.2, 21.5). Nothing here touches the network."""
import json
import re

import pytest
from fastapi.testclient import TestClient

from backend import auth, config, db, fallback, llm, main, seed_demo, topics


def _norm(s):
    return re.sub(r"\s+", " ", s.lower()).strip()


@pytest.mark.parametrize("topic", [t["id"] for t in topics.all_topics()])
def test_bank_is_complete_valid_and_grounded(topic):
    t = topics.get_topic(topic)
    raw = json.loads((config.ARTIFACTS / "fallback" / f"{topic}.json").read_text(encoding="utf-8"))
    assert len(raw["concepts"]) >= 6
    valid = fallback.concepts_for(topic)
    assert valid is not None and len(valid) == len(raw["concepts"])           # nothing is silently dropped by validation
    names, stems = set(), set()
    for c in valid:
        assert len(c.questions) == llm.N_VARIANTS == 5
        assert _norm(c.source_span) in _norm(t["text"])
        assert _norm(c.name) not in names
        names.add(_norm(c.name))
        for q in c.questions:
            assert _norm(q.stem) not in stems and q.stem.rstrip().endswith(("?", ":"))
            stems.add(_norm(q.stem))
    positions = [q.correct_index for c in valid for q in c.questions]
    assert len(set(positions)) == 4                                           # the right answer is not always in the same place
    assert max(positions.count(i) for i in range(4)) <= 0.4 * len(positions)


def test_unknown_or_missing_topic_returns_none():
    assert fallback.concepts_for(None) is None and fallback.concepts_for("nope") is None


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "LLM_MIN_INTERVAL_S", 0)
    monkeypatch.setattr(main, "now_ms", lambda: 1_800_000_000_000)
    db.init_db()
    with db.session() as conn:
        auth.create_user(conn, "p01", "pw-for-p01!", "student")
    return TestClient(main.app)


def _login(c):
    r = c.post("/api/auth/login", json={"username": "p01", "password": "pw-for-p01!"})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    c.post("/api/auth/consent", headers=h)
    return h


def _down(prompt):
    raise RuntimeError("LLM HTTP 503")


def test_topic_note_falls_back_when_the_model_fails(client, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _down)
    h = _login(client)
    r = client.post("/api/notes/topic", json={"topic_id": "korean_hangul"}, headers=h)
    s = client.get(f"/api/notes/{r.json()['note_id']}", headers=h).json()
    assert s["status"] == "done" and len(s["concepts"]) == 6
    q = client.get(f"/api/question/next?concept={s['concepts'][0]['concept_id']}", headers=h).json()
    assert len(q["options"]) == 4
    with db.session() as conn:                                                # the reserved final-test variant exists too
        assert conn.execute("SELECT COUNT(*) FROM questions WHERE is_final_test=1").fetchone()[0] == 6


def test_pasted_notes_still_fail_normally_and_flag_can_turn_fallback_off(client, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", _down)
    h = _login(client)
    r = client.post("/api/notes", json={"title": "Mine", "text": "Some pasted study notes about a topic that the bank does not cover at all."}, headers=h)
    assert client.get(f"/api/notes/{r.json()['note_id']}", headers=h).json()["status"] == "failed"
    monkeypatch.setattr(config, "USE_FALLBACK_BANK", False)
    r = client.post("/api/notes/topic", json={"topic_id": "photography_basics"}, headers=h)
    assert client.get(f"/api/notes/{r.json()['note_id']}", headers=h).json()["status"] == "failed"


def test_demo_seed_builds_an_offline_account_with_a_realistic_history(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "d.db")
    monkeypatch.setattr(main, "now_ms", lambda: 1_800_000_000_000)
    db.init_db()
    with db.session() as conn:
        r = seed_demo.seed(conn, "demo-pass-1", now_ms=1_800_000_000_000)
    assert r["concepts"] == 37 and r["password"] == "demo-pass-1"
    c = TestClient(main.app)
    tok = c.post("/api/auth/login", json={"username": "demo", "password": "demo-pass-1"}).json()
    assert tok["role"] == "demo" and tok["consent_ok"] is True
    h = {"Authorization": "Bearer " + tok["token"]}
    due = c.get("/api/due", headers=h).json()
    assert len(due["new"]) >= 4 and len(due["due"]) + len(due["upcoming"]) >= 8        # a mix of new, due and upcoming concepts
    assert all(0 < x["R_now"] <= 1 for x in due["due"] + due["upcoming"])
    cid = (due["due"] + due["upcoming"])[0]["concept_id"]
    curve = c.get(f"/api/retention/{cid}?theta=0.9", headers=h).json()                # the demo role can move theta
    assert curve["theta"] == 0.9 and len(curve["points"]) > 10
    with db.session() as conn:
        again = seed_demo.seed(conn, None, now_ms=1_800_000_000_000)                  # idempotent
        assert again["concepts"] == 0 and conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 37
        seed_demo.seed(conn, None, reset=True, now_ms=1_800_000_000_000)
        assert conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 37 and conn.execute("SELECT COUNT(*) FROM users WHERE username='demo'").fetchone()[0] == 1
