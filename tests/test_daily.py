"""The daily mixed test, the first quiz, the notes lock, the Remem Test, the what's-new note and the Remem Test upgrade."""
import json
import sqlite3

import pytest

from backend import config, daily, db, llm, main, remem_test_upgrade, topics
from tests.test_api import NOTE, answer, client, login, make_concepts  # noqa: F401  (client is a fixture)

PRACTICE = llm.N_PRACTICE


def _correct(qid):
    with db.session() as conn:
        return conn.execute("SELECT correct_idx FROM questions WHERE question_id=?", (qid,)).fetchone()[0]


def _take(c, h, url, right=lambda i: True, step=15_000):
    """Answer every question a test hands out. Returns (questions seen, final 'done' payload)."""
    seen = []
    while True:
        q = c.get(url, headers=h).json()
        if q["done"]:
            return seen, q
        assert q["position"] == len(seen) + 1 and "concept" not in q and "concept_id" not in q    # never a concept name or id
        seen.append(q)
        ci = _correct(q["question_id"])
        r = c.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": ci if right(len(seen)) else (ci + 1) % 4,
                                         "rt_ms": 6000, "idem_key": f"t-{q['question_id']}-{c.clock['t']}"}, headers=h)
        assert r.status_code == 200, r.text
        c.clock["t"] += step


def _concept_of(qid):
    with db.session() as conn:
        return conn.execute("SELECT concept_id FROM questions WHERE question_id=?", (qid,)).fetchone()[0]


def test_first_quiz_then_daily_test_mixed_and_nameless(client):
    h = login(client, "p01", "pw-for-p01!")
    cs = make_concepts(client, h)
    with db.session() as conn:
        note_id = conn.execute("SELECT note_id FROM notes").fetchone()[0]
    d = client.get("/api/due", headers=h).json()
    assert d["test"]["questions"] == 0 and d["first"] == [{"note_id": note_id, "title": "Bio", "questions": 2 * PRACTICE, "concepts": 2}]
    assert d["studied"] is False and d["whats_new"] is False

    seen, done = _take(client, h, f"/api/test/next?note={note_id}", right=lambda i: i % 3 != 0)
    assert len(seen) == 2 * PRACTICE and seen[0]["total"] == 2 * PRACTICE and seen[0]["concepts"] == 2
    order = [_concept_of(q["question_id"]) for q in seen]
    assert sorted(order) == sorted([c["concept_id"] for c in cs] * PRACTICE)
    assert all(a != b for a, b in zip(order, order[1:]))                     # mixed: never the same concept twice in a row (2 x 4 allows it)
    assert len({q["question_id"] for q in seen}) == len(seen)                # each question once
    assert done["total"] == 2 * PRACTICE and done["right"] == sum(1 for i in range(1, 9) if i % 3 != 0)
    assert {c["name"] for c in done["concepts"]} == {"Photosynthesis", "Chlorophyll"}         # names only at the end
    assert all(len(c["marks"]) == PRACTICE and c["next_due_in_days"] > 0 for c in done["concepts"])

    d = client.get("/api/due", headers=h).json()
    assert d["first"] == [] and d["test"]["questions"] == 0 and d["studied"] and d["next_test_in_days"] > 0
    with db.session() as conn:
        modes = [r[0] for r in conn.execute("SELECT mode FROM responses ORDER BY ts")]
    assert modes.count("first") == 2                                           # one first answer per concept, the rest of the quiz is review

    client.clock["t"] += 40 * config.MS_PER_DAY                               # everything is due now
    d = client.get("/api/due", headers=h).json()
    assert d["test"] == {"questions": 2 * PRACTICE, "answered": 0, "concepts": 2}
    a = client.get("/api/test/next", headers=h).json(); b = client.get("/api/test/next", headers=h).json()
    assert a == b                                                             # the order is stable while nothing is answered
    seen, done = _take(client, h, "/api/test/next")
    assert len(seen) == 2 * PRACTICE and done["right"] == 2 * PRACTICE
    assert client.get("/api/due", headers=h).json()["test"]["questions"] == 0


def test_stopping_halfway_keeps_the_rest_for_later(client):
    h = login(client, "p01", "pw-for-p01!")
    make_concepts(client, h)
    with db.session() as conn:
        note_id = conn.execute("SELECT note_id FROM notes").fetchone()[0]
    _take(client, h, f"/api/test/next?note={note_id}")
    client.clock["t"] += 40 * config.MS_PER_DAY
    for _ in range(3):                                                        # three answers, then the person stops
        q = client.get("/api/test/next", headers=h).json()
        assert client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": 0, "rt_ms": 5000, "idem_key": f"half-{q['question_id']}-{client.clock['t']}"}, headers=h).status_code == 200
        client.clock["t"] += 10_000
    d = client.get("/api/due", headers=h).json()["test"]
    assert d == {"questions": 2 * PRACTICE - 3, "answered": 3, "concepts": 2}
    q = client.get("/api/test/next", headers=h).json()
    assert q["position"] == 4 and q["total"] == 2 * PRACTICE


def test_daily_order_spreads_concepts():
    order = daily._order({1: 4, 2: 4, 3: 4}, "seed")
    assert sorted(order) == [1] * 4 + [2] * 4 + [3] * 4
    assert all(a != b for a, b in zip(order, order[1:]))
    assert order == daily._order({1: 4, 2: 4, 3: 4}, "seed") != daily._order({1: 4, 2: 4, 3: 4}, "other seed")


def test_notes_lock_after_the_quiz_and_one_last_read_for_earlier_people(client, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", lambda prompt: (_ for _ in ()).throw(RuntimeError("down")))   # the bank makes the quiz
    h = login(client, "p01", "pw-for-p01!")
    tid = "cognitive_biases"
    assert client.get(f"/api/topics/{tid}", headers=h).status_code == 200         # first read: open
    client.post("/api/notes/topic", json={"topic_id": tid}, headers=h)
    assert client.get(f"/api/topics/{tid}", headers=h).status_code == 403         # quiz made: locked
    with db.session() as conn:                                                     # someone who studied before the lock existed
        conn.execute("UPDATE notes SET last_read=1")
    t = {x["id"]: x for x in client.get("/api/topics", headers=h).json()["topics"]}
    assert t[tid]["reading"] == "last" and client.get("/api/due", headers=h).json()["last_read"] == [{"topic_id": tid, "title": "Cognitive Biases"}]
    r = client.get(f"/api/topics/{tid}", headers=h)
    assert r.status_code == 200 and r.json()["last_read"] is True
    assert client.get(f"/api/topics/{tid}", headers=h).status_code == 403         # used up on opening
    with db.session() as conn:
        conn.execute("UPDATE notes SET last_read=1")
        cid = conn.execute("SELECT concept_id FROM concepts LIMIT 1").fetchone()[0]
    answer(client, h, cid, True)                                                   # starting a test also uses it up
    assert client.get(f"/api/topics/{tid}", headers=h).status_code == 403


def test_remem_test_three_unseen_questions_shuffled_then_notes_unlock(client, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", lambda prompt: (_ for _ in ()).throw(RuntimeError("down")))
    h = login(client, "p01", "pw-for-p01!")
    client.post("/api/notes/topic", json={"topic_id": "nutrition_labels"}, headers=h)
    n = len(topics.get_topic("nutrition_labels") and json.loads((config.ARTIFACTS / "fallback" / "nutrition_labels.json").read_text(encoding="utf-8"))["concepts"])
    assert client.get("/api/final/next", headers=h).status_code == 403             # not open yet
    with db.session() as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('final_test_open','1')")
        practice = {r[0] for r in conn.execute("SELECT question_id FROM questions WHERE is_final_test=0")}
    fin = client.get("/api/due", headers=h).json()["final"]
    assert fin == {"open": True, "total": 3 * n, "answered": 0, "finished": False, "remaining": 3 * n}
    seen = []
    while True:
        q = client.get("/api/final/next", headers=h).json()
        if q["done"]:
            break
        assert "concept" not in q and q["question_id"] not in practice and q["position"] == len(seen) + 1
        seen.append(q["question_id"])
        assert client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": _correct(q["question_id"]), "rt_ms": 5000, "idem_key": f"remem-test-{q['question_id']}"}, headers=h).status_code == 200
    assert len(seen) == len(set(seen)) == 3 * n and q == {"done": True, "total": 3 * n, "right": 3 * n}
    concepts = [_concept_of(x) for x in seen]
    assert all(a != b for a, b in zip(concepts, concepts[1:]))                     # mixed: never the same concept twice in a row
    assert client.get("/api/due", headers=h).json()["final"]["finished"] is True
    assert client.get("/api/topics/nutrition_labels", headers=h).status_code == 200   # unlocked again


def test_whats_new_only_for_people_who_had_answered_before(client):
    h1, h2 = login(client, "p01", "pw-for-p01!"), login(client, "p02", "pw-for-p02!")
    c1 = make_concepts(client, h1)[0]["concept_id"]
    answer(client, h1, c1, True)
    client.clock["t"] += 60_000
    with db.session() as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('whats_new_cutoff', ?)", (str(client.clock["t"]),))
    client.clock["t"] += 60_000
    make_concepts(client, h2)                                                       # p02 made a quiz but had answered nothing before
    assert client.get("/api/due", headers=h1).json()["whats_new"] is True
    assert client.get("/api/due", headers=h2).json()["whats_new"] is False
    assert client.post("/api/whats-new/seen", headers=h1).status_code == 200
    assert client.get("/api/due", headers=h1).json()["whats_new"] is False           # shown once


def test_migration_gives_one_last_read_and_sets_the_cutoff(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA.replace(",\n  last_read INTEGER NOT NULL DEFAULT 0     -- 1 = one last read of a locked topic is still allowed (people who studied before the lock)", ""))
    c.execute("INSERT INTO users(username,pw_hash,salt,created_at) VALUES ('u',x'00',x'00',0)")
    c.execute("INSERT INTO notes(user_id,title,text,status,created_at,topic_id) VALUES (1,'a','t','done',0,'central_asia')")
    c.execute("INSERT INTO notes(user_id,title,text,status,created_at,topic_id) VALUES (1,'b','t','failed',0,'korean_hangul')")
    c.commit(); c.close()
    db.init_db(path)
    c = sqlite3.connect(path)
    assert [r[0] for r in c.execute("SELECT last_read FROM notes ORDER BY note_id")] == [1, 0]
    assert c.execute("SELECT value FROM settings WHERE key='whats_new_cutoff'").fetchone() is not None
    c.close()
    db.init_db(path)                                                                # a second start changes nothing
    c = sqlite3.connect(path)
    assert [r[0] for r in c.execute("SELECT last_read FROM notes ORDER BY note_id")] == [1, 0]


def _old_concept(conn, uid, note_id, name, stems, final_stem):
    cid = conn.execute("INSERT INTO concepts(user_id,note_id,name,arm,created_at) VALUES (?,?,?,'remem',0)", (uid, note_id, name)).lastrowid
    for i, st in enumerate(stems + [final_stem], start=1):
        conn.execute("INSERT INTO questions(concept_id,variant_no,stem,options_json,correct_idx,is_final_test,created_at) VALUES (?,?,?,?,0,?,0)",
                     (cid, i, st, '["a","b","c","d"]', 1 if i == 5 else 0))
    return cid


def test_upgrade_writes_the_rubric_test_and_updates_cached_results(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "u.db")
    db.init_db()
    written = json.loads((config.ARTIFACTS / "remem_test.json").read_text(encoding="utf-8"))["topics"]
    t = topics.get_topic("cognitive_biases")
    chunk = llm.split_chunks(t["text"])[0]
    names = list(written["cognitive_biases"])[:2]
    span = "The availability heuristic is judging how likely something is by how easily examples come to mind."
    old = {"concepts": [{"name": nm, "source_span": span, "questions": [{"stem": f"Old question {i} on {nm}?", "options": ["a", "b", "c", "d"], "correct_index": 0} for i in range(5)]}
                        for nm in names]}
    with db.session() as conn:
        conn.execute("INSERT INTO users(username,pw_hash,salt,created_at) VALUES ('u',x'00',x'00',0)")
        conn.execute("INSERT INTO notes(user_id,title,text,status,created_at,topic_id) VALUES (1,?,?,'done',0,'cognitive_biases')", (t["title"], t["text"]))
        a = _old_concept(conn, 1, 1, names[0], [f"Old question {i} on {names[0]}?" for i in range(4)], "Old question 4 on it?")
        b = _old_concept(conn, 1, 1, names[1], [f"Old question {i} on {names[1]}?" for i in range(4)], "Old question 4 on that?")
        qb = conn.execute("SELECT question_id FROM questions WHERE concept_id=? AND variant_no=5", (b,)).fetchone()[0]
        conn.execute("INSERT INTO responses(user_id,concept_id,question_id,idem_key,ts,correct,mode,arm) VALUES (1,?,?,'k-started',1,1,'final','remem')", (b, qb))
        conn.execute("INSERT INTO llm_cache VALUES (?,?,?,0)", (llm.chunk_hash(chunk), config.PROMPT_VERSION, json.dumps(old)))
        r = remem_test_upgrade.upgrade(conn)
        assert [x[0] for x in r["done"]] == [a] and [x[0] for x in r["started"]] == [b] and r["missing"] == [] and r["cache_rows"] == 1
        got = conn.execute("SELECT variant_no, stem, correct_idx, is_final_test FROM questions WHERE concept_id=? AND variant_no>4 ORDER BY variant_no", (a,)).fetchall()
        assert [tuple(g) for g in got] == [(5 + i, q["stem"], q["correct_index"], 1) for i, q in enumerate(written["cognitive_biases"][names[0]])]
        assert conn.execute("SELECT stem FROM questions WHERE question_id=?", (qb,)).fetchone()[0] == "Old question 4 on that?"   # a started test is left alone
        cached = json.loads(conn.execute("SELECT json FROM llm_cache").fetchone()[0])
        assert all(len(c["questions"]) == 7 and c["questions"][4]["stem"] == written["cognitive_biases"][c["name"]][0]["stem"] for c in cached["concepts"])
        assert [c.name for c in llm.validate_chunk(cached, chunk)] == names            # a future user gets exactly the same 7 questions
        again = remem_test_upgrade.upgrade(conn)                                        # running it twice changes nothing
        assert again["done"] == [] and again["same"] == 1 and again["cache_rows"] == 0


def test_upgrade_dry_run_does_not_touch_the_file(tmp_path):
    path = tmp_path / "old.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA.replace(",\n  last_read INTEGER NOT NULL DEFAULT 0     -- 1 = one last read of a locked topic is still allowed (people who studied before the lock)", ""))
    c.commit(); c.close()
    before = path.read_bytes()
    remem_test_upgrade.run(path, apply=False)
    assert path.read_bytes() == before                                              # not even the notes-lock migration
    remem_test_upgrade.run(path, apply=True)
    copies = list(tmp_path.glob("old.before-remem-test-*.db"))
    assert len(copies) == 1
    assert "last_read" not in {r[1] for r in sqlite3.connect(copies[0]).execute("PRAGMA table_info(notes)")}   # the backup is the file as it was
    assert "last_read" in {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(notes)")}


def test_upgrade_uses_the_bank_questions_for_concepts_made_from_the_bank(tmp_path, monkeypatch):
    """A concept made from the fallback bank gets the bank's Remem Test, even when a generated concept has the same name."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "b.db")
    db.init_db()
    bank = json.loads((config.ARTIFACTS / "fallback" / "cognitive_biases.json").read_text(encoding="utf-8"))
    con = next(c for c in bank["concepts"] if c["name"] == "Confirmation bias")
    written = json.loads((config.ARTIFACTS / "remem_test.json").read_text(encoding="utf-8"))["topics"]["cognitive_biases"]
    assert "Confirmation bias" in written                                           # the same name exists among the generated concepts
    with db.session() as conn:
        conn.execute("INSERT INTO users(username,pw_hash,salt,created_at) VALUES ('u',x'00',x'00',0)")
        conn.execute("INSERT INTO notes(user_id,title,text,status,created_at,topic_id) VALUES (1,'t','x','done',0,'cognitive_biases')")
        cid = _old_concept(conn, 1, 1, "Confirmation bias", [q["stem"] for q in con["questions"][:4]], "Some old fifth question?")
        remem_test_upgrade.upgrade(conn)
        new = [r[0] for r in conn.execute("SELECT stem FROM questions WHERE concept_id=? AND variant_no>4 ORDER BY variant_no", (cid,))]
    assert new == [q["stem"] for q in con["questions"][4:7]]


@pytest.mark.parametrize("source", ["written", "banks"])
def test_remem_test_questions_follow_the_rubric(source):
    """Every concept: three questions (one of each kind where labelled); four distinct options; one valid answer; balanced
    positions; and, for the banks where the practice questions are known, no answer already shown as a practice answer."""
    sets = []
    if source == "written":
        for tid, cs in json.loads((config.ARTIFACTS / "remem_test.json").read_text(encoding="utf-8"))["topics"].items():
            assert tid in {t["id"] for t in topics.all_topics()}
            for name, qs in cs.items():
                assert sorted(q["kind"] for q in qs) == ["apart", "explain", "use"], name
                sets.append((name, qs, []))
    else:
        for t in topics.all_topics():
            for c in json.loads((config.ARTIFACTS / "fallback" / f"{t['id']}.json").read_text(encoding="utf-8"))["concepts"]:
                sets.append((c["name"], c["questions"][4:7], c["questions"][:4]))
    positions = []
    for name, qs, practice in sets:
        assert len(qs) == 3, name
        shown = {pq["options"][pq["correct_index"]].lower() for pq in practice} - {name.lower(), "the " + name.lower()}
        for q in qs:
            llm.MCQ.model_validate(q)
            assert q["stem"].rstrip().endswith(("?", ":")), q["stem"]
            assert q["options"][q["correct_index"]].lower() not in shown, (name, q["stem"])
            positions.append(q["correct_index"])
    assert max(positions.count(i) for i in range(4)) <= 0.35 * len(positions)


def test_correct_answers_wait_for_the_end_and_mistakes_are_listed(client):
    h = login(client, "p01", "pw-for-p01!")
    make_concepts(client, h)
    with db.session() as conn:
        note_id = conn.execute("SELECT note_id FROM notes").fetchone()[0]
    q = client.get(f"/api/test/next?note={note_id}", headers=h).json()
    wrong = (_correct(q["question_id"]) + 1) % 4
    r = client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": wrong, "rt_ms": 5000, "idem_key": "wrong-answer-1"}, headers=h).json()
    assert r["correct"] is False and "correct_index" not in r and "source" not in r      # nothing about the right answer yet
    client.clock["t"] += 15_000
    for _ in range(20):                                                              # the rest answered correctly
        n = client.get(f"/api/test/next?note={note_id}", headers=h).json()
        if n["done"]:
            break
        assert client.post("/api/respond", json={"question_id": n["question_id"], "chosen_index": _correct(n["question_id"]), "rt_ms": 5000,
                                                 "idem_key": f"rest-of-test-{n['question_id']}"}, headers=h).status_code == 200
        client.clock["t"] += 15_000
    done = n
    assert len(done["missed"]) == 1 and done["right"] == done["total"] - 1
    m = done["missed"][0]
    assert m["stem"] == q["stem"] and m["chosen_index"] == wrong and m["correct_index"] == _correct(q["question_id"])


def test_no_practising_early(client):
    h = login(client, "p01", "pw-for-p01!")
    cid = make_concepts(client, h)[0]["concept_id"]
    assert answer(client, h, cid, True).status_code == 200                          # new concept: allowed
    client.clock["t"] += config.SESSION_GAP_MS + 60_000                              # the sitting is over and the concept is not due
    early = answer(client, h, cid, True)
    assert early.status_code == 409 and "isn't due" in early.json()["detail"]
    client.clock["t"] += 30 * config.MS_PER_DAY
    assert answer(client, h, cid, True).status_code == 200                          # due: allowed


def test_finished_remem_test_stays_finished_after_a_new_topic(client, monkeypatch):
    monkeypatch.setattr(llm, "_call_gemini", lambda prompt: (_ for _ in ()).throw(RuntimeError("down")))
    h = login(client, "p01", "pw-for-p01!")
    client.post("/api/notes/topic", json={"topic_id": "nutrition_labels"}, headers=h)
    with db.session() as conn:
        conn.execute("INSERT OR REPLACE INTO settings VALUES ('final_test_open','1')")
    for _ in range(100):
        q = client.get("/api/final/next", headers=h).json()
        if q["done"]:
            break
        assert client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": 0, "rt_ms": 5000, "idem_key": f"remem-test-{q['question_id']}"}, headers=h).status_code == 200
    client.post("/api/notes/topic", json={"topic_id": "central_asia"}, headers=h)     # a new topic adds unanswered test questions
    d = client.get("/api/due", headers=h).json()
    assert d["final"]["finished"] is True and d["final"]["remaining"] > 0
    assert client.get("/api/topics/nutrition_labels", headers=h).status_code == 200   # still unlocked


def test_cached_result_with_too_few_questions_is_made_again(client, monkeypatch):
    """An old saved result (5 questions per concept) for pasted notes no longer validates, so it is generated again."""
    h = login(client, "p01", "pw-for-p01!")
    chunk = llm.split_chunks(NOTE)[0]
    old = {"concepts": [{"name": "Old", "source_span": "plants convert light energy into chemical energy", "questions": [
        {"stem": f"Old question number {i}?", "options": ["a", "b", "c", "d"], "correct_index": 0} for i in range(5)]}]}
    with db.session() as conn:
        conn.execute("INSERT INTO llm_cache VALUES (?,?,?,0)", (llm.chunk_hash(chunk), config.PROMPT_VERSION, json.dumps(old)))
    cs = make_concepts(client, h)
    assert {c["name"] for c in cs} == {"Photosynthesis", "Chlorophyll"}


def test_app_files_always_revalidate_so_updates_reach_phones(client):
    assert client.get("/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/health").headers



def test_options_are_shuffled_per_person_and_answers_map_back(client):
    """Each person sees the options in their own fixed random order; a tap is marked against the stored answer."""
    from collections import Counter
    h = login(client, "p01", "pw-for-p01!")
    make_concepts(client, h)
    with db.session() as conn:
        note_id = conn.execute("SELECT note_id FROM notes").fetchone()[0]
        uid = conn.execute("SELECT user_id FROM users WHERE username='p01'").fetchone()[0]
    q = client.get(f"/api/test/next?note={note_id}", headers=h).json()
    assert q["shuffled"] is True and client.get(f"/api/test/next?note={note_id}", headers=h).json()["options"] == q["options"]   # stable
    with db.session() as conn:
        row = conn.execute("SELECT options_json, correct_idx FROM questions WHERE question_id=?", (q["question_id"],)).fetchone()
    stored = json.loads(row["options_json"])
    assert sorted(q["options"]) == sorted(stored)
    screen_pos = q["options"].index(stored[row["correct_idx"]])                    # where the right answer sits on this person's screen
    r = client.post("/api/respond", json={"question_id": q["question_id"], "chosen_index": screen_pos, "shuffled": True, "rt_ms": 4000,
                                          "idem_key": "shuffled-right-1"}, headers=h).json()
    assert r["correct"] is True and r["chosen_index"] == row["correct_idx"]          # stored as the original option
    # across many people and questions, a stored "always A" answer lands evenly on A to D
    spots = Counter(main.option_order(u, qid).index(0) for u in range(1, 60) for qid in range(1, 60))
    assert all(0.22 < spots[i] / sum(spots.values()) < 0.28 for i in range(4))
