"""Pilot-monitor statistics on a synthetic database."""
from backend import auth, db
from eval_dashboard import pilot

DAY = 86_400_000
NOW = 100 * DAY


def build(tmp_path):
    p = tmp_path / "t.db"
    db.init_db(p)
    with db.session(p) as c:
        u = auth.create_user(c, "user01", "x", "student")
        a = auth.create_user(c, "aryan", "x", "admin")
        c.execute("INSERT INTO notes(user_id,title,text,status,created_at) VALUES (?,?,?,?,?)", (u, "n1", "t", "done", NOW))
        c.execute("INSERT INTO notes(user_id,title,text,status,error,created_at) VALUES (?,?,?,?,?,?)", (u, "n2", "t", "failed", "timeout", NOW))
        for i, arm in enumerate(["remem", "sm2", "fixed"], start=1):
            c.execute("INSERT INTO concepts(user_id,note_id,name,arm,created_at) VALUES (?,?,?,?,?)", (u, 1, f"c{i}", arm, NOW))
            c.execute("INSERT INTO questions(concept_id,variant_no,stem,options_json,correct_idx,flagged,created_at) VALUES (?,?,?,?,?,?,?)",
                      (i, 1, "s", "[]", 0, 1 if i == 1 else 0, NOW))
        rows = [(1, 1, "k1", NOW - 2 * DAY, 1, 0.9, 3, "review", "remem"),
                (1, 1, "k2", NOW - 1 * DAY, 0, 0.4, 3, "review", "remem"),
                (2, 2, "k3", NOW - 1 * DAY, 1, 0.8, 5, "review", "sm2"),
                (3, 3, "k4", NOW - 1 * DAY, 1, None, 0, "first", "fixed"),
                (1, 1, "k5", NOW, 1, 0.95, 3, "review", "remem")]
        for cid, qid, k, ts, ok, pr, el, mode, arm in rows:
            c.execute("INSERT INTO responses(user_id,concept_id,question_id,idem_key,ts,correct,pred_R,elapsed_days,mode,arm) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (u, cid, qid, k, ts, ok, pr, el, mode, arm))
        # admin response must be excluded from all pilot stats
        c.execute("INSERT INTO responses(user_id,concept_id,question_id,idem_key,ts,correct,pred_R,elapsed_days,mode,arm) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (a, 1, 1, "adm", NOW, 0, 0.5, 1, "review", "remem"))
        c.execute("INSERT INTO state(user_id,concept_id,mastery,due_at) VALUES (?,?,?,?)", (u, 1, .5, NOW - 2 * DAY))
        c.execute("INSERT INTO state(user_id,concept_id,mastery,due_at) VALUES (?,?,?,?)", (u, 2, .5, NOW + 3 * DAY))
    return pilot.open_ro(p)


def test_pilot_stats(tmp_path):
    c = build(tmp_path)
    arm = pilot.by_arm(c).set_index("arm")
    assert arm.loc["remem", "review_answers"] == 3          # admin excluded
    assert abs(arm.loc["remem", "accuracy"] - 2 / 3) < 1e-9
    assert arm.loc["sm2", "review_answers"] == 1 and arm.loc["fixed", "review_answers"] == 0
    assert arm["concepts"].tolist() == [1, 1, 1]
    ad = pilot.adherence(c, NOW)
    assert ad["tracked"] == 2 and ad["overdue"] == 1 and abs(ad["median_days_late"] - 2) < 1e-9
    h = pilot.llm_health(c)
    assert h["notes_failed"] == 1 and h["note_fail_rate"] == 0.5 and h["flag_rate"] == 1 / 3
    cal = pilot.calibration(c)
    assert cal["n"].sum() == 4                              # pred_R present, student, review
    da = pilot.daily_activity(c)
    assert da["answers"].sum() == 5 and da["active_users"].max() == 1
    u = pilot.users_table(c, NOW).set_index("username")
    assert u.loc["user01", "n_answers"] == 0 and u.loc["user01", "notes"] == 2
    assert not pilot.final_test_open(c)
    assert len(pilot.recent_errors(c)) == 1


def test_empty_db(tmp_path):
    p = tmp_path / "e.db"; db.init_db(p); c = pilot.open_ro(p)
    assert pilot.daily_activity(c).empty and pilot.calibration(c).empty
    assert pilot.adherence(c, NOW)["tracked"] == 0
    assert len(pilot.by_arm(c)) == 3


def test_attention_list(tmp_path):
    c = build(tmp_path)
    items = pilot.attention(c, NOW)
    text = " ".join(i["text"] for i in items)
    assert "did not become a quiz" in text and "timeout" in text            # the failed note and its error
    assert any(i["level"] == "warn" for i in items)


def test_profiles_table_reads_the_signup_form_and_copes_with_old_databases(tmp_path):
    import json
    import sqlite3
    old = sqlite3.connect(":memory:")
    old.execute("CREATE TABLE users(user_id INTEGER, username TEXT, role TEXT)")
    assert pilot.profiles_table(old).empty                                      # a database from before the form existed
    old.execute("CREATE TABLE profiles(user_id INTEGER, full_name TEXT, contact TEXT, age INTEGER, known_topics TEXT, created_at INTEGER)")
    old.execute("INSERT INTO users VALUES (1,'user01','student'),(2,'boss','admin')")
    old.execute("INSERT INTO profiles VALUES (1,'A B','a@b.c',22,?,0),(2,'Admin','x@y.z',40,'[]',0)", (json.dumps(["central_asia"]),))
    t = pilot.profiles_table(old)
    assert t["username"].tolist() == ["user01"] and t["known_topics"].tolist() == ["central_asia"]
