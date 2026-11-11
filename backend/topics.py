"""Ready-made study topics so pilot users can start without pasting notes, with a balanced suggestion (spec D19)."""
from __future__ import annotations

import json
from functools import lru_cache

from backend import config

# id -> (file, subject, one-line blurb, rough minutes)
CATALOG = [
    ("korean_hangul", "korean_hangul.md", "Language", "Read the Korean alphabet: letters, sounds and how syllable blocks are built.", 8),
    ("photography_basics", "photography_basics.md", "Photography", "Aperture, shutter speed and ISO: how a camera controls light.", 8),
    ("central_asia", "central_asia.md", "Geography", "The five -stan countries: capitals, languages, landscapes and currencies.", 8),
    ("cognitive_biases", "cognitive_biases.md", "Psychology", "Six common mental shortcuts that quietly bend our judgement.", 7),
    ("how_gps_works", "how_gps_works.md", "Technology", "How satellites and clocks pin down your position.", 8),
    ("nutrition_labels", "nutrition_labels.md", "Health", "Read serving sizes, macros, sugar and salt on food packaging.", 7),
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
    """Least-chosen topic (distinct student users) that this user has not done and did not say they already know; ties rotate by user_id so cohorts spread evenly."""
    counts = {t["id"]: 0 for t in _load()}
    for r in conn.execute("""SELECT n.topic_id, COUNT(DISTINCT n.user_id) AS k FROM notes n JOIN users u USING(user_id)
                             WHERE n.topic_id IS NOT NULL AND u.role='student' GROUP BY n.topic_id"""):
        if r["topic_id"] in counts:
            counts[r["topic_id"]] = r["k"]
    mine = {r["topic_id"] for r in conn.execute("SELECT topic_id FROM notes WHERE user_id=? AND topic_id IS NOT NULL", (user_id,))}
    row = conn.execute("SELECT known_topics FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    if row:                                                  # never suggest a topic the person said they already know well
        mine |= set(json.loads(row["known_topics"]))
    ids = [t["id"] for t in _load()]
    free = [(counts[i], (k - user_id) % len(ids), i) for k, i in enumerate(ids) if i not in mine]
    return min(free)[2] if free else None
