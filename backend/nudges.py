"""Playful reminder copy (food-delivery-app style), picked from what the student is actually about to forget.

Fairness: the copy never depends on the scheduling arm. The concept named in a message is drawn from everything due today,
whatever arm it belongs to, and the send rule (when, how often) stays in backend.push. Only the wording changes.

Each message is chosen from a "situation" (coming back after a gap, on a streak, one question, a big pile, or a normal day),
then rotated by day so nobody sees the same line two days running. The template id goes into reminders.detail, so the
dashboard can later check which lines actually bring people back.
"""
from __future__ import annotations

import hashlib
import random

from backend import config, daily

# {n} questions waiting · {concept} a due concept · {topic} its note title · {name} first name · {streak} days · {away} days
T = {
    "comeback": [
        ("cb1", "Knock knock 🚪", "It's your memory of {concept}. It's been {away} days. We miss each other."),
        ("cb2", "{name}, your brain called 📞", "It said {topic} is getting fuzzy. {n} quick questions fixes that."),
        ("cb3", "Come back, all is forgiven 🥺", "{n} questions, no judgement. {topic} kept your seat warm."),
        ("cb4", "Plot twist: you still remember", "Bet you get most of these {n} right. Prove the forgetting curve wrong."),
    ],
    "streak": [
        ("st1", "{streak}-day streak 🔥 Don't drop it", "{n} questions stand between you and day {next}."),
        ("st2", "Streak status: still sizzling 🍳", "Day {next} is waiting. {topic} is on the menu."),
        ("st3", "Consistency? Very hot right now 🌶️", "{streak} days strong. {n} more questions to keep the flame going."),
    ],
    "one": [
        ("on1", "Just 1 question. Literally one ☝️", "Faster than replying 'ok' on WhatsApp. It's on {concept}."),
        ("on2", "Tiny order, big impact 🛵", "1 question on {concept}, delivered in under 10 seconds."),
        ("on3", "One question walked into your phone…", "…and asked about {concept}. Don't leave it on read."),
    ],
    "pile": [
        ("pl1", "Your reviews are piling up like dishes 🍽️", "{n} questions waiting. Start with one, the rest go fast."),
        ("pl2", "Order of {n} questions, ready for pickup 📦", "Delivered fresh from {topic}. Cancellation not recommended."),
        ("pl3", "Houston, we have a backlog 🚀", "{n} questions in orbit. 5 minutes brings them all home."),
    ],
    "normal": [
        ("nm1", "Your {topic} is getting cold 🥶", "Reheat it with {n} quick questions. Best served fresh."),
        ("nm2", "Brain snack ready in 2 mins 🍿", "{n} questions on {topic}. Zero calories, full gains."),
        ("nm3", "{concept}: remember me? 👀", "We'll know in {n} questions. No pressure. (Some pressure.)"),
        ("nm4", "Fresh out of the memory oven 🥐", "{n} questions, hot and ready. {topic} is the chef's special."),
        ("nm5", "Your memory has entered the chat 💬", "It wants to talk about {concept}. {n} questions, 2 minutes."),
        ("nm6", "Forgetting curve says hi 📉", "Right on time. {n} questions on {topic} flattens it back out."),
        ("nm7", "Delivery partner arriving 🛵", "{n} questions on {topic}, arriving at your brain now."),
    ],
}

PILE_AT = 12          # this many questions or more counts as a pile
COMEBACK_AFTER = 3    # days since the last answer


def _first_name(full: str | None) -> str:
    w = (full or "").strip().split()
    return w[0].capitalize() if w else "Hey"


def context(conn, uid: int, now: int, n: int) -> dict:
    """Facts for the copy: a due concept and its topic, first name, current streak and days away."""
    due = daily.test_concepts(conn, uid, now)
    rng = random.Random(f"{uid}:{daily._local_day(now)}")
    concept = topic = None
    if due:
        row = conn.execute("""SELECT c.name, n.title FROM concepts c LEFT JOIN notes n USING(note_id) WHERE c.concept_id=?""",
                           (rng.choice(due),)).fetchone()
        if row:
            concept, topic = row[0], row[1]
    p = conn.execute("SELECT full_name FROM profiles WHERE user_id=?", (uid,)).fetchone()
    days = sorted({daily._local_day(r[0]) for r in conn.execute("SELECT ts FROM responses WHERE user_id=?", (uid,))}, reverse=True)
    today = daily._local_day(now)
    streak, d = 0, today - (0 if days and days[0] == today else 1)
    for day in days:
        if day == d:
            streak += 1; d -= 1
        elif day < d:
            break
    away = today - days[0] if days else 0
    topic = (topic or "").split(":")[0].split("(")[0].strip()[:30]        # "Korean Hangul: letters and sounds" -> "Korean Hangul"
    return {"n": n, "concept": (concept or "what you studied")[:40], "topic": topic or "Your revision", "name": _first_name(p and p[0]),
            "streak": streak, "next": streak + 1, "away": away}


def situation(ctx: dict) -> str:
    if ctx["away"] >= COMEBACK_AFTER:
        return "comeback"
    if ctx["streak"] >= 2:
        return "streak"
    if ctx["n"] == 1:
        return "one"
    if ctx["n"] >= PILE_AT:
        return "pile"
    return "normal"


def pick(ctx: dict, uid: int, day: int, last_id: str | None = None) -> tuple[str, str, str]:
    """(template id, title, body). Rotates by day and never repeats yesterday's line when there is a choice."""
    pool = T[situation(ctx)]
    start = int(hashlib.sha1(f"{uid}".encode()).hexdigest(), 16) + day
    for k in range(len(pool)):
        tid, title, body = pool[(start + k) % len(pool)]
        if tid != last_id or len(pool) == 1:
            return tid, title.format(**ctx), body.format(**ctx)
    raise AssertionError("unreachable")


def plain(n: int) -> dict:
    """The original neutral wording, kept for when there is no context (and for the REMEM_NUDGES=0 switch)."""
    body = ("1 question is waiting." if n == 1 else f"{n} questions are waiting.") + " A few minutes now keeps what you studied fresh."
    return {"title": "Today's test is ready", "body": body, "count": n, "url": "./#/"}


def build(conn, uid: int, now: int, n: int) -> dict:
    if not config.NUDGES_ON:
        return plain(n)
    last = conn.execute("SELECT detail FROM reminders WHERE user_id=? AND kind='due' AND detail LIKE 'tpl:%' ORDER BY ts DESC LIMIT 1",
                        (uid,)).fetchone()
    last_id = last[0].split(";")[0][4:] if last else None
    tid, title, body = pick(context(conn, uid, now, n), uid, daily._local_day(now), last_id)
    return {"title": title, "body": body, "count": n, "url": "./#/", "tpl": tid}
