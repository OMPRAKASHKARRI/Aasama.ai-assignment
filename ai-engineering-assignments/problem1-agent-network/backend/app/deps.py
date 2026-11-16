"""FastAPI dependencies: API-key authentication and rate limiting."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Agent
from app.security import hash_api_key
from app.services import ratelimit


def get_current_agent(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"), db: Session = Depends(get_db)
) -> Agent:
    if not x_api_key or len(x_api_key) > 200:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid API key",
                            headers={"WWW-Authenticate": "ApiKey"})
    agent = db.scalar(select(Agent).where(Agent.api_key_hash == hash_api_key(x_api_key)))
    if agent is None or not agent.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or invalid API key",
                            headers={"WWW-Authenticate": "ApiKey"})
    return agent


def rate_limited_agent(agent: Agent = Depends(get_current_agent)) -> Agent:
    allowed, retry = ratelimit.hit(f"agent:{agent.id}", get_settings().rate_limit_per_minute, 60)
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "rate limit exceeded",
                            headers={"Retry-After": str(retry)})
    return agent


def register_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    allowed, retry = ratelimit.hit(f"register:{ip}", get_settings().register_rate_limit_per_hour, 3600)
    if not allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many registrations from this address",
                            headers={"Retry-After": str(retry)})
