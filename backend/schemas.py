from __future__ import annotations

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=200)


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=40, max_length=20000)


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=80)
    contact: str = Field(min_length=3, max_length=120)
    age: int = Field(ge=10, le=100)
    known_topics: list[str] = Field(default_factory=list, max_length=20)


class TopicIn(BaseModel):
    topic_id: str = Field(min_length=1, max_length=40)


class RespondIn(BaseModel):
    question_id: int
    chosen_index: int = Field(ge=0, le=3)
    rt_ms: int = Field(ge=0, le=3_600_000)
    idem_key: str = Field(min_length=8, max_length=80)


class FlagIn(BaseModel):
    question_id: int
