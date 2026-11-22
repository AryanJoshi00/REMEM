"""Playful reminder copy (food-delivery-app style, Hinglish, Bollywood nods), picked from what the student is actually about to forget.

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
# Each line is (id, title, body) or (id, title, body, slot): a slot line goes out only in that part of the day
# (am 9-12, pm 12-17, eve 17-21; reminders never go out outside 9 am to 9 pm).
T = {
    "comeback": [
        ("cb1", "Knock knock 🚪", "It's your memory of {concept}. It's been {away} days. We miss each other."),
        ("cb2", "{name}, your brain called 📞", "It said {topic} is getting fuzzy. {n} quick questions fixes that."),
        ("cb3", "Itne din kahan the? 🥺", "{away} din ho gaye. {topic} abhi bhi darwaze pe wait kar raha hai."),
        ("cb4", "Plot twist: you still remember", "Bet you get most of these {n} right. Prove the forgetting curve wrong."),
        ("cb5", "💔 {concept} left you on seen", "{away} din se reply nahi kiya. {n} questions mein patch-up ho jayega."),
        ("cb6", "Picture abhi baaki hai mere dost 🎬", "{topic}: The Comeback. {n} questions, now streaming."),
    ],
    "streak": [
        ("st1", "{streak}-day streak 🔥 Don't drop it", "{n} questions stand between you and day {next}."),
        ("st2", "Streak status: still sizzling 🍳", "Day {next} is waiting. {topic} is on the menu."),
        ("st3", "{streak} din ka streak 🔥 Nazar na lage", "{n} questions karo, streak zinda rakho."),
        ("st4", "Main apni favourite hoon 💁", "{streak} din se tum bhi ho. {n} questions for day {next}."),
    ],
    "one": [
        ("on1", "Just 1 question. Literally one ☝️", "Faster than replying 'ok' on WhatsApp. It's on {concept}."),
        ("on2", "Bas ek sawaal. Pakka. ☝️", "{concept}. 10 seconds. Promise."),
        ("on3", "One question walked into your phone…", "…and asked about {concept}. Don't leave it on read."),
    ],
    "pile": [
        ("pl1", "Kitne questions the? 🤠", "{n}, sardar. Aur tum abhi tak shuru nahi kiye?"),
        ("pl2", "Utha le re baba… 🙏", "…nahi, sirf {n} questions utha le. {topic} wait kar raha hai."),
        ("pl3", "Your reviews are piling up like dishes 🍽️", "{n} questions waiting. Start with one, the rest go fast."),
        ("pl4", "Houston, we have a backlog 🚀", "{n} questions in orbit. 5 minutes brings them all home."),
    ],
    "normal": [
        ("bw1", "Kitne topics the? …2? 😅", "Pappi bhai mat bano. {n} questions on {topic}."),
        ("bw2", "Ghajini mat bano 🧠", "REMEM hai na. {n} questions on {concept}, aur yaad pakka."),
        ("bw3", "All is well? {topic} isn't 🫠", "{n} questions karo, phir sach mein all is well."),
        ("bw4", "Memory ko jaadu ki jhappi do 🤗", "{n} questions on {concept}. Tension nahi lene ka."),
        ("bw5", "{concept} bhoolna mushkil hi nahi… 😎", "…namumkin hai. Bas {n} questions kar lo."),
        ("bw6", "Dimaag bhool bhulaiyaa ban gaya? 🌀", "Rasta {concept} se hoke jaata hai. {n} questions."),
        ("bw7", "Ja {name}, jee le apni zindagi 🚂", "…bas pehle {n} questions. Train baad mein pakadna."),
        ("bw8", "Kitne questions the? 🤠", "{n}, sardar. Bas {n}. Ab toh kar lo."),
        ("ap1", "📩 New follow request from {concept}", "Accept karo, warna it'll ghost you for real."),
        ("ap2", "👀 {topic} viewed your profile", "And then asked: \"Mujhe bhool gaye?\" {n} questions to answer."),
        ("ap3", "🔔 {name}, someone mentioned you", "Your brain. It said \"{topic}?? kya tha woh?\""),
        ("hg1", "Padhai ki, ab yaad bhi rakh lo 😌", "{n} questions. Chai thandi hone se pehle done."),
        ("hg2", "Tumhara {topic} ka gyaan ro raha hai 🥲", "2 minute ka time do, chup ho jayega."),
        ("hg3", "Memory ka recharge khatam hone wala hai 🔋", "{n} questions = full battery."),
        ("nm1", "Your {topic} is getting cold 🥶", "Reheat it with {n} quick questions. Best served fresh."),
        ("nm2", "{concept}: remember me? 👀", "We'll know in {n} questions. No pressure. (Some pressure.)"),
        ("nm3", "Forgetting curve says hi 📉", "Right on time. {n} questions on {topic} flattens it back out."),
        ("am1", "Chai + {topic} = perfect combo ☕", "{n} questions before the day gets busy.", "am"),
        ("pm1", "3 PM slump? Your brain needs a snack 🍪", "{n} questions on {concept}. Zero calories.", "pm"),
        ("ev1", "Netflix can wait 2 minutes 📺", "{n} questions first, then guilt-free binge-watching.", "eve"),
        ("ev2", "Day ka last kaam 🌙", "{n} questions and you're officially productive today.", "eve"),
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


def slot(hour: int) -> str:
    return "am" if hour < 12 else "pm" if hour < 17 else "eve"


def pick(ctx: dict, uid: int, day: int, last_id: str | None = None, hour: int = 10) -> tuple[str, str, str]:
    """(template id, title, body). Lines for another part of the day are skipped; the rest rotate by day, and yesterday's
    line is never repeated when there is a choice."""
    now = slot(hour)
    pool = [t[:3] for t in T[situation(ctx)] if len(t) == 3 or t[3] == now]
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
    hour = ((now + config.TZ_OFFSET_MS) % config.MS_PER_DAY) // 3_600_000
    tid, title, body = pick(context(conn, uid, now, n), uid, daily._local_day(now), last_id, hour)
    return {"title": title, "body": body, "count": n, "url": "./#/", "tpl": tid}
