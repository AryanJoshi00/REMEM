"""Pre-written quiz material for the three ready-made topics (spec 21.2: a fallback bank keeps the demo running offline).

The bank is stored in artifacts/fallback/<topic id>.json in the same shape the language model returns and is checked with
the very same validation (schema, four distinct options, source sentence present in the notes, five distinct questions
per concept). It is used only when generating a quiz for a ready-made topic fails, or by the demo seed script; notes the
user pastes themselves never use it.
"""
from __future__ import annotations

import json

from backend import config, llm, topics


def concepts_for(topic_id: str | None):
    """Validated concepts for a topic, or None when the topic has no bank or the bank fails validation."""
    if not topic_id:
        return None
    path = config.ARTIFACTS / "fallback" / f"{topic_id}.json"
    topic = topics.get_topic(topic_id)
    if topic is None or not path.exists():
        return None
    try:
        concepts = llm.validate_chunk(json.loads(path.read_text(encoding="utf-8")), topic["text"])
    except Exception:
        return None
    return concepts or None
