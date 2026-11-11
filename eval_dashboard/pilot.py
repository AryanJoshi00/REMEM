"""Pilot-monitor statistics computed from a (copy of the) REMEM SQLite database. Pure functions, no Streamlit."""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd

IST_OFFSET_MS = 5.5 * 3600 * 1000


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
      FROM users u ORDER BY u.user_id""")
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


def by_arm(conn) -> pd.DataFrame:
    """Arms are randomised per concept. Review answers only (the pilot's comparison); descriptive, not significance."""
    r = _df(conn, """SELECT arm, correct, was_due, elapsed_days FROM responses r JOIN users u USING(user_id)
                     WHERE u.role='student' AND mode='review'""")
    c = _df(conn, """SELECT c.arm, COUNT(*) AS concepts FROM concepts c JOIN users u USING(user_id)
                     WHERE u.role='student' GROUP BY c.arm""").set_index("arm")["concepts"]
    rows = []
    for arm in ["remem", "sm2", "fixed"]:
        x = r[r["arm"] == arm]
        rows.append({
            "arm": arm,
            "concepts": int(c.get(arm, 0)),
            "review_answers": len(x),
            "accuracy": float(x["correct"].mean()) if len(x) else np.nan,
            "mean_gap_days": float(x["elapsed_days"].mean()) if len(x) else np.nan,
        })
    return pd.DataFrame(rows)


def calibration(conn, bins=(0, .5, .6, .7, .8, .9, 1.0001)) -> pd.DataFrame:
    """Predicted probability vs observed correctness for review answers (REMEM's own predictions, all arms)."""
    r = _df(conn, """SELECT pred_R, correct FROM responses r JOIN users u USING(user_id)
                     WHERE u.role='student' AND mode='review' AND pred_R IS NOT NULL""")
    if r.empty:
        return pd.DataFrame(columns=["bin", "n", "predicted", "observed"])
    r["bin"] = pd.cut(r["pred_R"], bins=list(bins), right=False)
    g = r.groupby("bin", observed=True)
    out = pd.DataFrame({"n": g.size(), "predicted": g["pred_R"].mean(), "observed": g["correct"].mean()}).reset_index()
    out["bin"] = out["bin"].astype(str)
    return out


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
