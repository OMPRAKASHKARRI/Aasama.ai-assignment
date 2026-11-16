from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import rate_limited_agent
from app.models import Agent, Notification
from app.routers._common import screen_untrusted
from app.schemas import FeedbackIn, NotificationOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _mine(db: Session, notification_id: uuid.UUID, agent: Agent) -> Notification:
    """Only the recipient may touch a notification; anything else is a 404 so ids can't be probed."""
    n = db.get(Notification, notification_id)
    if n is None or n.agent_id != agent.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    return n


@router.get("", response_model=list[NotificationOut], summary="Your notification inbox")
def inbox(
    delivery_status: Literal["queued", "delivered", "failed"] | None = None,
    unread: bool = False, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
    agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db),
) -> list[Notification]:
    q = select(Notification).where(Notification.agent_id == agent.id)
    if delivery_status:
        q = q.where(Notification.delivery_status == delivery_status)
    if unread:
        q = q.where(Notification.opened_at.is_(None))
    q = q.order_by(Notification.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(q).unique())


@router.post("/{notification_id}/ack", response_model=NotificationOut, summary="Mark a notification as opened")
def acknowledge(notification_id: uuid.UUID, agent: Agent = Depends(rate_limited_agent),
                db: Session = Depends(get_db)) -> Notification:
    n = _mine(db, notification_id, agent)
    if n.opened_at is None:  # idempotent: first open wins
        n.opened_at = datetime.now(timezone.utc)
        db.commit()
    return n


@router.post("/{notification_id}/feedback", response_model=NotificationOut,
             summary="Tell the router whether this notification was relevant")
def feedback(notification_id: uuid.UUID, body: FeedbackIn, agent: Agent = Depends(rate_limited_agent),
             db: Session = Depends(get_db)) -> Notification:
    n = _mine(db, notification_id, agent)
    screen_untrusted(note=body.note)
    now = datetime.now(timezone.utc)
    n.feedback = "relevant" if body.relevant else "not_relevant"
    n.feedback_note = body.note
    n.feedback_at = now
    if n.opened_at is None:
        n.opened_at = now
    db.commit()
    return n
