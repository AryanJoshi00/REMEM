"""Pilot-monitor statistics computed from a (copy of the) REMEM SQLite database. Pure functions, no Streamlit."""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

IST_OFFSET_MS = 5.5 * 3600 * 1000
GAP_DAYS = 30 / 1440          # the session rule: answers to a concept less than 30 minutes apart belong to one test


def open_ro(path) -> sqlite3.Connection:
    """Load the database into memory and release the file at once, so the file can be replaced while the page is open
    (Windows refuses to overwrite a file that is still held open)."""
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    mem = sqlite3.connect(":memory:")
    try:
        src.backup(mem)
    finally:
        src.close()
    mem.row_factory = sqlite3.Row
    return mem


def _df(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


def _day(ts_ms: pd.Series) -> pd.Series:
    return pd.to_datetime(ts_ms + IST_OFFSET_MS, unit="ms").dt.date


def users_table(conn, now_ms: int) -> pd.DataFrame:
    df = _df(conn, """
      SELECT u.user_id, u.username, u.role, u.active, u.consent_at, u.n_answers, u.created_at,
             (SELECT COUNT(*) FROM notes n WHERE n.user_id=u.user_id) AS notes,
             (SELECT COUNT(*) FROM concepts c WHERE c.user_id=u.user_id) AS concepts,
             (SELECT MAX(ts) FROM responses r WHERE r.user_id=u.user_id) AS last_ts
      FROM users u WHERE u.role != 'demo' ORDER BY u.user_id""")           # test accounts (role demo) are never shown
    df["consented"] = df["consent_at"].notna()
    df["days_since_last"] = ((now_ms - df["last_ts"]) / 86_400_000).round(1)
    return df.drop(columns=["consent_at", "created_at", "last_ts"])


def profiles_table(conn) -> pd.DataFrame:
    """Sign-up form answers (name, contact, age, topics already known). Empty if the database predates the form."""
    cols = ["username", "full_name", "contact", "age", "known_topics"]
    try:
        df = _df(conn, """SELECT u.username, p.full_name, p.contact, p.age, p.known_topics
                          FROM profiles p JOIN users u USING(user_id) WHERE u.role='student' ORDER BY u.user_id""")
    except Exception:
        return pd.DataFrame(columns=cols)
    df["known_topics"] = df["known_topics"].map(lambda s: ", ".join(json.loads(s)) or "none")
    return df


def daily_activity(conn) -> pd.DataFrame:
    r = _df(conn, "SELECT ts, user_id, mode, correct FROM responses r JOIN users u USING(user_id) WHERE u.role='student'")
    if r.empty:
        return pd.DataFrame(columns=["day", "answers", "reviews", "active_users"])
    r["day"] = _day(r["ts"])
    g = r.groupby("day")
    return pd.DataFrame({
        "answers": g.size(),
        "reviews": g.apply(lambda x: int((x["mode"] == "review").sum()), include_groups=False),
        "active_users": g["user_id"].nunique(),
    }).reset_index()


def review_tests(conn) -> pd.DataFrame:
    """One row per concept per review test: the evidence of memory.

    A concept's answers in one test (gaps under 30 minutes) form one review. Its prediction is REMEM's pred_R at the first
    answer, the moment the gap ended; the outcome is the share of its questions answered correctly in that test. Since the
    right answers are shown only at the end of a test, every answer in it is a clean recall attempt, so no single question
    decides the result. Reviews from before that change (cut-off: 'whats_new_cutoff') showed each right answer straight away,
    so only their first answer counts. First quizzes are learning, not memory, and are left out.
    """
    cut = conn.execute("SELECT value FROM settings WHERE key='whats_new_cutoff'").fetchone()
    cutoff = int(cut["value"]) if cut else None
    r = _df(conn, """SELECT r.user_id, r.concept_id, r.ts, r.correct, r.pred_R, r.elapsed_days, r.mode, r.arm
                     FROM responses r JOIN users u USING(user_id) WHERE u.role='student' AND r.mode IN ('first','review')
                     ORDER BY r.user_id, r.concept_id, r.ts, r.response_id""")
    cols = ["user_id", "concept_id", "arm", "start_ts", "pred_R", "gap_days", "n", "right", "score"]
    if r.empty:
        return pd.DataFrame(columns=cols)
    gap_ms = GAP_DAYS * 86_400_000
    new_test = (r["user_id"] != r["user_id"].shift()) | (r["concept_id"] != r["concept_id"].shift()) | (r["ts"] - r["ts"].shift() > gap_ms)
    r["test"] = new_test.cumsum()
    rows = []
    for _, g in r.groupby("test", sort=False):
        first = g.iloc[0]
        if first["mode"] != "review" or pd.isna(first["pred_R"]):
            continue
        g = g if cutoff is None or first["ts"] >= cutoff else g.iloc[:1]
        rows.append({"user_id": int(first["user_id"]), "concept_id": int(first["concept_id"]), "arm": first["arm"], "start_ts": int(first["ts"]),
                     "pred_R": float(first["pred_R"]), "gap_days": float(first["elapsed_days"]), "n": len(g), "right": int(g["correct"].sum()),
                     "score": float(g["correct"].mean())})
    return pd.DataFrame(rows, columns=cols)


def by_arm(conn) -> pd.DataFrame:
    """Arms are randomised per concept. Per arm: how many reviews (one per concept per test), how many answers they hold, and
    the share answered correctly. Descriptive, not significance."""
    t = review_tests(conn)
    c = _df(conn, """SELECT c.arm, COUNT(*) AS concepts FROM concepts c JOIN users u USING(user_id)
                     WHERE u.role='student' GROUP BY c.arm""").set_index("arm")["concepts"]
    rows = []
    for arm in ["remem", "sm2", "fixed"]:
        x = t[t["arm"] == arm]
        n = int(x["n"].sum()) if len(x) else 0
        rows.append({
            "arm": arm,
            "concepts": int(c.get(arm, 0)),
            "review_tests": len(x),
            "review_answers": n,
            "accuracy": float(x["right"].sum() / n) if n else np.nan,
            "mean_gap_days": float(x["gap_days"].mean()) if len(x) else np.nan,
        })
    return pd.DataFrame(rows)


def calibration(conn, bins=(0, .5, .6, .7, .8, .9, 1.0001)) -> pd.DataFrame:
    """REMEM's predicted chance of a correct answer at the start of each review against the share actually answered correctly
    in that review (all arms). n counts answers."""
    t = review_tests(conn)
    if t.empty:
        return pd.DataFrame(columns=["bin", "n", "predicted", "observed"])
    t["bin"] = pd.cut(t["pred_R"], bins=list(bins), right=False)
    t["wp"] = t["pred_R"] * t["n"]
    g = t.groupby("bin", observed=True)
    out = pd.DataFrame({"n": g["n"].sum(), "predicted": g["wp"].sum() / g["n"].sum(), "observed": g["right"].sum() / g["n"].sum()}).reset_index()
    out["bin"] = out["bin"].astype(str)
    return out


def calibration_by_gap(conn, bins=(0, 1, 2, 4, 7, 10_000)) -> pd.DataFrame:
    """The same predicted-against-observed comparison, split by days since the last review (all arms). Shows where in time
    the forgetting model holds and where it drifts. n counts answers."""
    t = review_tests(conn)
    cols = ["gap", "reviews", "n", "predicted", "observed"]
    if t.empty:
        return pd.DataFrame(columns=cols)
    labels = [f"{a}–{b} days" if b < 10_000 else f"{a}+ days" for a, b in zip(bins, bins[1:])]
    t["gap"] = pd.cut(t["gap_days"], bins=list(bins), right=False, labels=labels)
    t["wp"] = t["pred_R"] * t["n"]
    g = t.groupby("gap", observed=True)
    out = pd.DataFrame({"reviews": g.size(), "n": g["n"].sum(), "predicted": g["wp"].sum() / g["n"].sum(),
                        "observed": g["right"].sum() / g["n"].sum()}).reset_index()
    out["gap"] = out["gap"].astype(str)
    return out[cols]


def balance(conn) -> pd.DataFrame:
    """Evidence that the arms are comparable: concepts per arm per student, and first-quiz accuracy per arm (learning before
    any scheduling happened, so it should be similar across arms)."""
    c = _df(conn, """SELECT c.user_id, c.arm FROM concepts c JOIN users u USING(user_id) WHERE u.role='student'""")
    f = _df(conn, """SELECT r.arm, r.correct FROM responses r JOIN users u USING(user_id) WHERE u.role='student' AND r.mode='first'""")
    rows = []
    for arm in ["remem", "sm2", "fixed"]:
        per = c[c["arm"] == arm].groupby("user_id").size().reindex(c["user_id"].unique(), fill_value=0) if not c.empty else pd.Series(dtype=int)
        x = f[f["arm"] == arm] if not f.empty else f
        rows.append({"arm": arm, "concepts": int((c["arm"] == arm).sum()) if not c.empty else 0,
                     "per_student_min": int(per.min()) if len(per) else 0, "per_student_max": int(per.max()) if len(per) else 0,
                     "first_quiz_answers": len(x), "first_quiz_accuracy": float(x["correct"].mean()) if len(x) else np.nan})
    return pd.DataFrame(rows)


def adherence(conn, now_ms: int) -> dict:
    """Of the concepts a student has learned, how many are currently overdue, and how late are the overdue ones."""
    s = _df(conn, """SELECT s.due_at FROM state s JOIN users u USING(user_id) WHERE u.role='student' AND s.due_at IS NOT NULL""")
    if s.empty:
        return {"tracked": 0, "overdue": 0, "overdue_share": np.nan, "median_days_late": np.nan}
    late = (now_ms - s["due_at"]) / 86_400_000
    over = late[late > 0]
    return {"tracked": len(s), "overdue": int(len(over)), "overdue_share": float(len(over) / len(s)),
            "median_days_late": float(over.median()) if len(over) else 0.0}


def llm_health(conn) -> dict:
    n = _df(conn, "SELECT status, COUNT(*) AS k FROM notes GROUP BY status").set_index("status")["k"].to_dict()
    q = _df(conn, "SELECT COUNT(*) AS n, COALESCE(SUM(flagged),0) AS f FROM questions").iloc[0]
    tot = sum(n.values())
    return {"notes_total": tot, "notes_done": n.get("done", 0), "notes_failed": n.get("failed", 0),
            "notes_pending": n.get("pending", 0),
            "note_fail_rate": (n.get("failed", 0) / tot) if tot else np.nan,
            "questions": int(q["n"]), "flagged": int(q["f"]),
            "flag_rate": (q["f"] / q["n"]) if q["n"] else np.nan}


def recent_errors(conn, limit=15) -> pd.DataFrame:
    return _df(conn, """SELECT datetime(created_at/1000,'unixepoch','+330 minutes') AS time_ist, title, error
                        FROM notes WHERE status='failed' ORDER BY note_id DESC LIMIT ?""", (limit,))


def final_test_open(conn) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key='final_test_open'").fetchone()
    return bool(row and str(row[0]) in ("1", "true", "True"))


def attention(conn, now_ms: int, stale_days: float = 3.0) -> list[dict]:
    """Plain-language list of things the owner should look at. Each item: {level: 'warn' | 'info', text}."""
    out = []
    u = users_table(conn, now_ms)
    s = u[(u["role"] == "student") & (u["active"] == 1)]
    waiting = s[~s["consented"]]["username"].tolist()
    if waiting:
        out.append({"level": "info", "text": f"{len(waiting)} not signed in yet or consent not accepted: {', '.join(waiting)}."})
    idle = s[s["consented"] & (s["n_answers"] == 0)]["username"].tolist()
    if idle:
        out.append({"level": "info", "text": f"Accepted consent but answered nothing: {', '.join(idle)}."})
    silent = s[(s["n_answers"] > 0) & (s["days_since_last"] > stale_days)]
    if len(silent):
        names = ", ".join(f"{r.username} ({r.days_since_last:.0f} days)" for r in silent.itertuples())
        out.append({"level": "warn", "text": f"No answers for more than {stale_days:g} days: {names}."})
    h = llm_health(conn)
    if h["notes_failed"]:
        err = recent_errors(conn, 1)
        why = f" Latest error: {err.iloc[0]['error']}" if len(err) and err.iloc[0]["error"] else ""
        out.append({"level": "warn", "text": f"{h['notes_failed']} of {h['notes_total']} notes did not become a quiz.{why}"})
    if h["questions"] >= 10 and h["flag_rate"] > 0.10:
        out.append({"level": "warn", "text": f"Students flagged {h['flagged']} of {h['questions']} questions as bad ({h['flag_rate']:.0%})."})
    return out
