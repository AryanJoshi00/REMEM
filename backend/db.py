"""SQLite store (WAL). One short-lived connection per request / operation."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from backend import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  pw_hash BLOB NOT NULL,
  salt BLOB NOT NULL,
  role TEXT NOT NULL DEFAULT 'student',      -- student | demo | admin
  active INTEGER NOT NULL DEFAULT 1,
  consent_at INTEGER,
  consent_version TEXT,
  ability REAL NOT NULL DEFAULT 0.67,
  n_answers INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(user_id),
  expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
  note_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(user_id),
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',    -- pending | done | failed
  error TEXT,
  created_at INTEGER NOT NULL,
  topic_id TEXT
);
CREATE TABLE IF NOT EXISTS concepts (
  concept_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(user_id),
  note_id INTEGER REFERENCES notes(note_id),
  name TEXT NOT NULL,
  source_span TEXT,
  arm TEXT NOT NULL DEFAULT 'remem',         -- remem | sm2 | fixed
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
  question_id INTEGER PRIMARY KEY AUTOINCREMENT,
  concept_id INTEGER NOT NULL REFERENCES concepts(concept_id),
  variant_no INTEGER NOT NULL,
  stem TEXT NOT NULL,
  options_json TEXT NOT NULL,
  correct_idx INTEGER NOT NULL,
  is_final_test INTEGER NOT NULL DEFAULT 0,
  flagged INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS responses (
  response_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(user_id),
  concept_id INTEGER NOT NULL REFERENCES concepts(concept_id),
  question_id INTEGER NOT NULL REFERENCES questions(question_id),
  idem_key TEXT UNIQUE NOT NULL,
  ts INTEGER NOT NULL,
  correct INTEGER NOT NULL,
  rt_ms INTEGER,
  pred_R REAL,
  elapsed_days REAL,
  mode TEXT NOT NULL,                        -- first | review | final
  arm TEXT NOT NULL,
  was_due INTEGER,
  stability_after REAL,
  mastery_after REAL,
  result_json TEXT
);
CREATE TABLE IF NOT EXISTS state (
  user_id INTEGER NOT NULL,
  concept_id INTEGER NOT NULL,
  mastery REAL NOT NULL,
  n_sessions INTEGER NOT NULL DEFAULT 0,
  n_responses INTEGER NOT NULL DEFAULT 0,
  last_ts INTEGER,
  stability_days REAL,
  t_review_days REAL,
  due_at INTEGER,
  remem_due_at INTEGER,
  sm2_ef REAL NOT NULL DEFAULT 2.5,
  sm2_reps INTEGER NOT NULL DEFAULT 0,
  sm2_interval REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, concept_id)
);
CREATE TABLE IF NOT EXISTS llm_cache (
  chunk_hash TEXT PRIMARY KEY,
  prompt_version TEXT NOT NULL,
  json TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  user_id INTEGER,
  event TEXT NOT NULL,
  detail TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_resp_user ON responses(user_id, concept_id, ts);
CREATE INDEX IF NOT EXISTS idx_q_concept ON questions(concept_id);
"""


def connect(path=None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path=None) -> None:
    with connect(path) as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(notes)")}
        if "topic_id" not in cols:                       # light migration for databases created before topics existed
            c.execute("ALTER TABLE notes ADD COLUMN topic_id TEXT")


@contextmanager
def session(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def audit(conn, event: str, user_id=None, detail: str = "", ts: int | None = None) -> None:
    import time
    conn.execute("INSERT INTO audit(ts,user_id,event,detail) VALUES (?,?,?,?)", (ts or int(time.time() * 1000), user_id, event, detail))
