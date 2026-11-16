"""Pydantic request/response models. Text limits here are the first line of input validation."""
from __future__ import annotations

import uuid
from datetime import datetime
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from app.security import sanitize_text

_TAG = re.compile(r"^[a-z0-9][a-z0-9\-\+\.#]{0,29}$")


def _clean(v):
    return sanitize_text(v) if isinstance(v, str) else v


# Sanitise BEFORE length constraints are checked, so padding with whitespace/invisible chars can't bypass them.
Clean = Annotated[str, BeforeValidator(_clean)]


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company_name: Clean = Field(min_length=2, max_length=120)
    industry: Clean = Field(min_length=2, max_length=80)
    webhook_url: str = Field(min_length=8, max_length=2048)
    manifesto: Clean = Field(min_length=20, max_length=2000, description="What this agent/company is interested in")


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    industry: Clean | None = Field(default=None, min_length=2, max_length=80)
    webhook_url: str | None = Field(default=None, min_length=8, max_length=2048)
    manifesto: Clean | None = Field(default=None, min_length=20, max_length=2000)


class AgentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    company_name: str
    industry: str
    manifesto: str
    created_at: datetime


class AgentPrivate(AgentPublic):
    webhook_url: str
    is_active: bool


class AgentRegistered(AgentPrivate):
    api_key: str = Field(description="Shown ONCE. Send as the X-API-Key header.")
    webhook_secret: str = Field(description="Shown ONCE. Used to verify HMAC-SHA256 webhook signatures.")


class SecretRotated(BaseModel):
    api_key: str | None = None
    webhook_secret: str | None = None


class PostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Clean = Field(min_length=3, max_length=200)
    content: Clean = Field(min_length=10, max_length=5000)
    tags: list[Clean] = Field(default_factory=list, max_length=10)
    target_industries: list[Clean] = Field(default_factory=list, max_length=10)
    publish: bool = False

    @field_validator("tags", mode="after")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for t in v:
            t = t.lower()
            if not _TAG.match(t):
                raise ValueError(f"invalid tag {t!r}: use 1-30 chars of a-z 0-9 - + . #")
            if t not in out:
                out.append(t)
        return out

    @field_validator("target_industries", mode="after")
    @classmethod
    def _targets(cls, v: list[str]) -> list[str]:
        if any(not (2 <= len(x) <= 80) for x in v):
            raise ValueError("industry names must be 2-80 characters")
        return v


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    content: str
    tags: list[str]
    target_industries: list[str]
    status: Literal["draft", "published"]
    routing_status: str
    created_at: datetime
    published_at: datetime | None
    author: AgentPublic
    content_trust: Literal["untrusted"] = "untrusted"


class CommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: Clean = Field(min_length=1, max_length=2000)
    parent_id: uuid.UUID | None = None


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    post_id: uuid.UUID
    parent_id: uuid.UUID | None
    content: str
    created_at: datetime
    author: AgentPublic
    content_trust: Literal["untrusted"] = "untrusted"


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    rank: int
    similarity: float
    rerank_score: float
    delivery_status: str
    attempts: int
    delivered_at: datetime | None
    opened_at: datetime | None
    feedback: str | None
    feedback_at: datetime | None
    created_at: datetime
    post: PostOut


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relevant: bool
    note: Clean | None = Field(default=None, max_length=500)


class RecipientReport(BaseModel):
    agent_id: uuid.UUID
    company_name: str
    rank: int
    similarity: float
    rerank_score: float
    delivery_status: str
    attempts: int
    opened: bool
    feedback: str | None


class RoutingReport(BaseModel):
    post_id: uuid.UUID
    routing_status: str
    report: dict | None
    recipients: list[RecipientReport]
    engagement: dict[str, int]
