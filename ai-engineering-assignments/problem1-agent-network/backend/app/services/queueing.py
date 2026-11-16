"""Redis/RQ plumbing. Jobs are referenced by dotted path so this module never imports job code."""
from __future__ import annotations

import logging
from functools import lru_cache
from uuid import UUID

from redis import Redis
from rq import Queue, Retry

from app.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)


def get_queue() -> Queue:
    return Queue(get_settings().queue_name, connection=get_redis())


def enqueue_route_post(post_id: UUID) -> str:
    job = get_queue().enqueue(
        "app.jobs.route_post_job", str(post_id), job_timeout=300, result_ttl=3600, failure_ttl=86400,
        retry=Retry(max=3, interval=[5, 30, 120]),
    )
    return job.id


def enqueue_delivery(notification_id: UUID) -> str:
    s = get_settings()
    retries = max(0, s.webhook_max_attempts - 1)
    base = s.backoff_intervals or [10]
    intervals = [base[min(i, len(base) - 1)] for i in range(retries)]
    job = get_queue().enqueue(
        "app.jobs.deliver_notification_job", str(notification_id), job_timeout=60, result_ttl=3600,
        failure_ttl=86400, retry=Retry(max=retries, interval=intervals) if retries else None,
    )
    return job.id
