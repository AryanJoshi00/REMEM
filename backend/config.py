"""Runtime configuration (env + constants). Secrets come only from the environment / .env."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("REMEM_DB", ROOT / "data" / "pilot" / "remem.db"))
ARTIFACTS = ROOT / "artifacts"
WEBAPP = ROOT / "webapp"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Models are tried in order; free-tier models are retired/overloaded without notice (spec 21.3), so keep a fallback list.
GEMINI_MODELS = [m.strip() for m in os.getenv("GEMINI_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite,gemini-flash-lite-latest").split(",") if m.strip()]
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "40"))
LLM_MIN_INTERVAL_S = float(os.getenv("LLM_MIN_INTERVAL_S", "4"))
PROMPT_VERSION = "v1"

THETA = float(os.getenv("REMEM_THETA", "0.85"))
T_MIN_DAYS = float(os.getenv("REMEM_T_MIN_DAYS", "1.0"))
T_MAX_DAYS = float(os.getenv("REMEM_T_MAX_DAYS", "180"))
FIXED_INTERVAL_DAYS = 3.0

MAX_STUDENT_ACCOUNTS = 10
NOTES_PER_DAY = int(os.getenv("REMEM_NOTES_PER_DAY", "3"))
USE_FALLBACK_BANK = os.getenv("REMEM_FALLBACK", "1") == "1"       # ready-made topics fall back to the pre-written quiz when the language model fails
MAX_NOTE_CHARS = 6000
MAX_CHUNKS_PER_NOTE = 6
SESSION_TTL_HOURS = 24 * 7
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_S = 600

# Population defaults used for brand-new notes concepts (taken from the EdNet training split; spec 9.7)
DEFAULT_ABILITY = 0.67
DEFAULT_DIFFICULTY = 0.33
MCQ_GUESS = 0.25            # four-option multiple choice
MS_PER_DAY = 86_400_000
SESSION_GAP_MS = 30 * 60 * 1000
ABILITY_GAMMA = 0.9
CONSENT_VERSION = "v1"
