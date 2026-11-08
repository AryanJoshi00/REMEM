"""Ready-made study topics so pilot users can start without pasting notes, with a balanced suggestion (spec D19)."""
from __future__ import annotations

from functools import lru_cache

from backend import config

# id -> (file, subject, one-line blurb, rough minutes)
CATALOG = [
    ("photosynthesis", "photosynthesis.md", "Biology", "How plants turn light, water and CO₂ into food and oxygen.", 8),
    ("newtons_laws", "newtons_laws.md", "Physics", "Inertia, F = ma and action–reaction, with everyday examples.", 8),
    ("acids_bases_salts", "acids_bases_salts.md", "Chemistry", "Properties, pH scale, indicators and neutralisation.", 10),
]


@lru_cache(maxsize=None)
def _load():
    out = []
    for tid, fname, subject, blurb, minutes in CATALOG:
        raw = (config.ARTIFACTS / "topics" / fname).read_text(encoding="utf-8").strip()
        head, _, body = raw.partition("\n")
        title = head.split("(")[0].strip()
        out.append({"id": tid, "title": title, "subject": subject, "blurb": blurb, "minutes": minutes,
                    "text": raw[:config.MAX_NOTE_CHARS], "words": len(body.split())})
    return out


def all_topics() -> list[dict]:
    return _load()


def get_topic(tid: str) -> dict | None:
    return next((t for t in _load() if t["id"] == tid), None)


def suggest(conn, user_id: int) -> str | None:
    """Least-chosen topic (distinct student users) that this user has not done; ties rotate by user_id so cohorts spread evenly."""
    counts = {t["id"]: 0 for t in _load()}
    for r in conn.execute("""SELECT n.topic_id, COUNT(DISTINCT n.user_id) AS k FROM notes n JOIN users u USING(user_id)
                             WHERE n.topic_id IS NOT NULL AND u.role='student' GROUP BY n.topic_id"""):
        if r["topic_id"] in counts:
            counts[r["topic_id"]] = r["k"]
    mine = {r["topic_id"] for r in conn.execute("SELECT topic_id FROM notes WHERE user_id=? AND topic_id IS NOT NULL", (user_id,))}
    ids = [t["id"] for t in _load()]
    free = [(counts[i], (k - user_id) % len(ids), i) for k, i in enumerate(ids) if i not in mine]
    return min(free)[2] if free else None
