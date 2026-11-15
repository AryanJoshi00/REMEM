"""Notes -> concepts -> MCQs via Gemini (spec 21.2, 21.3).

The LLM supplies CONTENT only. Everything it returns is validated before storage; results are cached by
chunk hash + prompt version; calls are rate-limited. The key is read from the environment and never logged.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import threading
import time

import requests
from pydantic import BaseModel, Field, ValidationError, field_validator

from backend import config, db

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
N_EASY = 4                     # practice, easier: recognise, define, a direct example
N_HARD = 4                     # practice, harder: a new situation, why it happens, telling it apart, working something out
N_PRACTICE = N_EASY + N_HARD   # asked in the daily tests: one easier and one harder per concept per review
N_TEST = 3                     # never shown before the Remem Test (the delayed test)
N_VARIANTS = N_PRACTICE + N_TEST
N_BANK = N_EASY + N_TEST       # the fallback banks hold 4 easier practice questions and the 3 Remem Test questions


def layout(n: int) -> list[tuple[int, int]]:
    """(is_final_test, level) for each of a concept's n questions, in order: the last N_TEST are the Remem Test, the first
    N_EASY are easier practice (level 1), anything between is harder practice (level 2). Works for 11 (generated) and 7 (banks)."""
    return [(1, 0) if i >= n - N_TEST else (0, 1 if i < N_EASY else 2) for i in range(n)]

_lock = threading.Lock()
_last_call = 0.0


class MCQ(BaseModel):
    stem: str = Field(min_length=8)
    options: list[str]
    correct_index: int

    @field_validator("options")
    @classmethod
    def four_distinct(cls, v):
        v = [o.strip() for o in v]
        if len(v) != 4 or len(set(o.lower() for o in v)) != 4 or any(not o for o in v):
            raise ValueError("need exactly 4 distinct non-empty options")
        return v

    @field_validator("correct_index")
    @classmethod
    def in_range(cls, v):
        if v not in (0, 1, 2, 3):
            raise ValueError("correct_index must be 0-3")
        return v


class ConceptOut(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    source_span: str = Field(min_length=8)
    questions: list[MCQ]


class ChunkOut(BaseModel):
    concepts: list[ConceptOut]


PROMPT = """You turn study notes into quiz material.
Read the NOTES below and return ONLY JSON of this shape:
{{"concepts":[{{"name":"short concept name","source_span":"an exact quote of 8-25 words copied from the notes that this concept is based on","questions":[{{"stem":"question text","options":["A","B","C","D"],"correct_index":0}}]}}]}}
Rules:
- 2 to 4 distinct concepts per notes chunk; each concept must be clearly present in the notes.
- Each concept needs exactly {n} multiple-choice questions with DIFFERENT wording and angle.
- Questions 1 to 4 are easier practice: recognise or define the idea, and a direct example.
- Questions 5 to 8 are harder practice that make the learner think: a NEW situation where the idea must be applied, why
  something happens or what follows from it, telling the idea apart from a similar one, and working something out or
  putting steps in order. Not simple recall of a sentence.
- Questions 9, 10 and 11 are a later memory test and must test understanding, not recall of wording: 9 puts the idea to use
  in a NEW situation the notes do not mention; 10 asks why something happens or what follows from it (never "what is X");
  11 tells the idea apart from a similar one, puts steps in order, or works something out. They must not repeat or give
  away any practice question.
- No question may ask about a detail of an example in the notes (such as a price or a name used only as an illustration).
- Exactly 4 options per question, only one correct, plausible distractors, correct_index is 0-3 and should vary.
- Use only facts stated in or directly implied by the notes. No trick questions.
- source_span must be copied character-for-character from the notes.

NOTES:
\"\"\"
{chunk}
\"\"\""""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def split_chunks(text: str, target_words: int = 300, max_chunks: int = config.MAX_CHUNKS_PER_NOTE) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    chunks, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > target_words:
            chunks.append("\n\n".join(cur)); cur, n = [], 0
        cur.append(p); n += w
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks[:max_chunks]


def chunk_hash(chunk: str) -> str:
    return hashlib.sha256(f"{config.PROMPT_VERSION}|{chunk}".encode()).hexdigest()   # model-independent: cached content stays valid


def validate_chunk(raw: dict, chunk: str, n: int | None = None) -> list[ConceptOut]:
    """Schema check + grounding check (source span must occur in the notes) + n distinct questions (N_VARIANTS by default)."""
    n = n or N_VARIANTS
    parsed = ChunkOut.model_validate(raw)
    nchunk = _norm(chunk)
    good = []
    for c in parsed.concepts:
        if _norm(c.source_span) not in nchunk:
            continue                                     # grounding failure
        qs = []
        seen = set()
        for q in c.questions:
            key = _norm(q.stem)
            if key in seen:
                continue
            seen.add(key); qs.append(q)
        if len(qs) < n:
            continue
        good.append(ConceptOut(name=c.name.strip(), source_span=c.source_span.strip(), questions=qs[:n]))
    return good


def dedupe_concepts(concepts: list[ConceptOut]) -> list[ConceptOut]:
    out: list[ConceptOut] = []
    for c in concepts:
        if any(difflib.SequenceMatcher(None, _norm(c.name), _norm(o.name)).ratio() > 0.85 for o in out):
            continue
        out.append(c)
    return out


def _call_gemini(prompt: str) -> str:
    """One rate-limited call with model fallback and short retries. Raises RuntimeError with a key-free message."""
    global _last_call
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.4}}
    last = "no model available"
    for model in config.GEMINI_MODELS:
        for attempt in range(2):
            with _lock:
                wait = config.LLM_MIN_INTERVAL_S - (time.time() - _last_call)
                if wait > 0:
                    time.sleep(wait)
                _last_call = time.time()
            try:
                r = requests.post(f"{API_ROOT}/models/{model}:generateContent", headers={"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"},
                                  json=body, timeout=config.LLM_TIMEOUT_S)
            except requests.RequestException as e:
                last = f"LLM network error ({type(e).__name__})"
                break                                         # try the next model
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"LLM HTTP {r.status_code}"
                if attempt == 0:
                    time.sleep(5)
                    continue
                break
            if r.status_code != 200:
                last = f"LLM HTTP {r.status_code}"
                break                                         # e.g. 404 retired model: next one
            try:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception:
                last = "LLM response had no text"
                break
    raise RuntimeError(last)


def generate_for_chunk(chunk: str, caller=None) -> list[ConceptOut]:
    """Database access is in short separate sessions so no write lock is held while waiting for the LLM (SEC-001)."""
    caller = caller or _call_gemini
    h = chunk_hash(chunk)
    with db.session() as conn:
        row = conn.execute("SELECT json FROM llm_cache WHERE chunk_hash=? AND prompt_version=?", (h, config.PROMPT_VERSION)).fetchone()
    if row:
        try:
            good = validate_chunk(json.loads(row["json"]), chunk)
        except (ValidationError, json.JSONDecodeError, ValueError):
            good = []
        if good:
            return good                                  # an older or broken entry (too few questions per concept) is made again below
    last_err = None
    for _ in range(2):                                   # one retry on invalid output
        try:
            text = caller(PROMPT.format(n=N_VARIANTS, chunk=chunk))
            raw = json.loads(text)
            good = validate_chunk(raw, chunk)
            if good:
                with db.session() as conn:
                    conn.execute("INSERT OR REPLACE INTO llm_cache(chunk_hash,prompt_version,json,created_at) VALUES (?,?,?,?)",
                                 (h, config.PROMPT_VERSION, json.dumps(raw), int(time.time() * 1000)))
                return good
            last_err = "no concept passed validation"
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            last_err = f"invalid output: {type(e).__name__}"
    raise RuntimeError(last_err or "generation failed")


def generate_for_note(text: str, caller=None) -> list[ConceptOut]:
    out: list[ConceptOut] = []
    errors = 0
    for ch in split_chunks(text[:config.MAX_NOTE_CHARS]):
        try:
            out.extend(generate_for_chunk(ch, caller))
        except RuntimeError:
            errors += 1
    out = dedupe_concepts(out)
    if not out:
        raise RuntimeError("Could not generate valid questions from these notes. Try again later or shorten the text.")
    return out
