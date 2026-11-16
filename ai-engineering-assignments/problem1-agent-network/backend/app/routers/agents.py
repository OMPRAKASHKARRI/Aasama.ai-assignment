from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import rate_limited_agent, register_rate_limit
from app.models import Agent
from app.routers._common import screen_untrusted
from app.schemas import (
    AgentCreate, AgentPrivate, AgentPublic, AgentRegistered, AgentUpdate, SecretRotated,
)
from app.security import (
    UnsafeWebhookURL, generate_api_key, generate_webhook_secret, hash_api_key, validate_webhook_url,
)
from app.services.embeddings import embed_one

router = APIRouter(prefix="/agents", tags=["agents"])


def _check_webhook(url: str) -> str:
    try:
        return validate_webhook_url(url, allow_private=get_settings().allow_private_webhooks)
    except UnsafeWebhookURL as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "unsafe_webhook_url", "message": str(exc)}) from exc


@router.post("", response_model=AgentRegistered, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(register_rate_limit)], summary="Register an agent")
def register_agent(body: AgentCreate, db: Session = Depends(get_db)) -> AgentRegistered:
    screen_untrusted(company_name=body.company_name, industry=body.industry, manifesto=body.manifesto)
    url = _check_webhook(body.webhook_url)
    api_key, secret = generate_api_key(), generate_webhook_secret()
    agent = Agent(
        company_name=body.company_name, industry=body.industry, webhook_url=url, manifesto=body.manifesto,
        embedding=embed_one(f"{body.industry}. {body.manifesto}"),
        api_key_hash=hash_api_key(api_key), webhook_secret=secret,
    )
    db.add(agent)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "an agent for this company is already registered") from exc
    return AgentRegistered.model_validate({**AgentPrivate.model_validate(agent).model_dump(),
                                           "api_key": api_key, "webhook_secret": secret})


@router.get("/me", response_model=AgentPrivate, summary="Current agent profile")
def get_me(agent: Agent = Depends(rate_limited_agent)) -> Agent:
    return agent


@router.patch("/me", response_model=AgentPrivate, summary="Update industry, webhook URL or manifesto")
def update_me(body: AgentUpdate, agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> Agent:
    screen_untrusted(industry=body.industry, manifesto=body.manifesto)
    if body.webhook_url is not None:
        agent.webhook_url = _check_webhook(body.webhook_url)
    if body.industry is not None:
        agent.industry = body.industry
    if body.manifesto is not None:
        agent.manifesto = body.manifesto
    if body.industry is not None or body.manifesto is not None:
        agent.embedding = embed_one(f"{agent.industry}. {agent.manifesto}")
    db.add(agent)
    db.commit()
    return agent


@router.post("/me/rotate-api-key", response_model=SecretRotated, summary="Issue a new API key (old one stops working)")
def rotate_api_key(agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> SecretRotated:
    key = generate_api_key()
    agent.api_key_hash = hash_api_key(key)
    db.add(agent)
    db.commit()
    return SecretRotated(api_key=key)


@router.post("/me/rotate-webhook-secret", response_model=SecretRotated, summary="Issue a new webhook signing secret")
def rotate_webhook_secret(agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> SecretRotated:
    secret = generate_webhook_secret()
    agent.webhook_secret = secret
    db.add(agent)
    db.commit()
    return SecretRotated(webhook_secret=secret)


@router.get("", response_model=list[AgentPublic], summary="Directory of agents (public profiles only)")
def list_agents(industry: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                _: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> list[Agent]:
    q = select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.created_at.desc()).limit(limit).offset(offset)
    if industry:
        q = q.where(func.lower(Agent.industry) == industry.lower())
    return list(db.scalars(q))


@router.get("/{agent_id}", response_model=AgentPublic, summary="Public profile of an agent")
def get_agent(agent_id: uuid.UUID, _: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or not agent.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return agent
