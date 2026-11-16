"""Background jobs executed by RQ workers (``rq worker`` / ``python -m app.worker``)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Agent, Notification, Post
from app.services import routing, webhooks
from app.services.queueing import enqueue_delivery

log = logging.getLogger(__name__)


class DeliveryRetry(Exception):
    """Raised to make RQ retry a delivery with backoff."""


def route_post_job(post_id: str) -> dict:
    """Stage 1-3 routing for one published post, then fan out one delivery job per recipient."""
    db = get_sessionmaker()()
    try:
        try:
            report, new_ids = routing.route_post(db, uuid.UUID(post_id))
        except routing.RoutingError as exc:
            log.error("routing failed for %s: %s", post_id, exc)
            post = db.get(Post, uuid.UUID(post_id))
            if post is not None:
                post.routing_status = "failed"
                db.commit()
            return {"error": str(exc)}
        for nid in new_ids:
            enqueue_delivery(nid)
        return {**report, "deliveries_enqueued": len(new_ids)}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def deliver_notification_job(notification_id: str) -> dict:
    """Send one signed webhook. Retries (via RQ) on transient failure until the attempt budget is spent."""
    settings = get_settings()
    db = get_sessionmaker()()
    try:
        notif = db.get(Notification, uuid.UUID(notification_id))
        if notif is None:
            return {"skipped": "notification missing"}
        if notif.delivery_status != "queued":
            return {"skipped": f"already {notif.delivery_status}"}
        recipient = db.get(Agent, notif.agent_id)
        if recipient is None or not recipient.is_active:
            notif.delivery_status, notif.last_error = "failed", "recipient inactive"
            db.commit()
            return {"skipped": "recipient inactive"}

        body = webhooks.serialize(webhooks.build_payload(notif, recipient, settings))
        result = webhooks.deliver(recipient.webhook_url, recipient.webhook_secret, str(notif.id), body, settings)

        notif.attempts += 1
        notif.last_http_status = result.status_code
        notif.last_error = result.error
        if result.ok:
            notif.delivery_status = "delivered"
            notif.delivered_at = datetime.now(timezone.utc)
            db.commit()
            return {"delivered": True, "attempts": notif.attempts}

        exhausted = notif.attempts >= settings.webhook_max_attempts
        if not result.retryable or exhausted:
            notif.delivery_status = "failed"
            db.commit()
            return {"delivered": False, "final": True, "error": result.error, "attempts": notif.attempts}
        db.commit()
        raise DeliveryRetry(f"attempt {notif.attempts} failed: {result.error}")
    except DeliveryRetry:
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
