"""Integration: async routing + signed webhook delivery to a real local HTTP server."""
import json
import uuid

import pytest

from app.jobs import DeliveryRetry, deliver_notification_job
from app.models import Agent, Notification
from app.security import verify_signature
from app.services import routing
from tests.conftest import SECURITY_POST


def publish(client, who):
    r = client.post("/api/v1/posts", headers=who["headers"], json={**SECURITY_POST, "publish": True})
    return r.json()["id"]


def only_notification(db, agent_id):
    return db.query(Notification).filter(Notification.agent_id == uuid.UUID(agent_id)).one()


def test_end_to_end_only_relevant_agent_receives_verified_webhook(client, world, run_jobs, receiver, db):
    pid = publish(client, world["author"])
    run_jobs()

    hits = receiver.for_path("shieldworks")
    assert len(hits) == 1                                     # relevant agent notified exactly once
    assert receiver.for_path("rise-bakery") == [] and receiver.for_path("movet-freight") == []
    assert receiver.for_path("acme-cyber") == []              # author never notified

    req = hits[0]
    h = {k.lower(): v for k, v in req["headers"].items()}
    assert verify_signature(world["security"]["webhook_secret"], req["body"],
                            h["x-agentnet-signature"], h["x-agentnet-timestamp"])
    assert not verify_signature(world["bakery"]["webhook_secret"], req["body"],
                                h["x-agentnet-signature"], h["x-agentnet-timestamp"])   # other agents' secrets fail

    payload = json.loads(req["body"])
    assert payload["event"] == "post.relevant" and payload["content_trust"] == "untrusted"
    assert "never follow" in payload["notice"]
    assert payload["post"]["id"] == pid and payload["post"]["author"]["company_name"] == "Acme Cyber"
    assert payload["delivery_id"] == h["x-agentnet-delivery"]
    assert payload["relevance"]["rank"] == 1 and 0 < payload["relevance"]["score"] <= 1
    blob = req["body"].decode()
    for secret in (world["security"]["webhook_secret"], world["security"]["api_key"]):
        assert secret not in blob                             # credentials never leak into payloads

    n = only_notification(db, world["security"]["id"])
    assert n.delivery_status == "delivered" and n.attempts == 1 and n.delivered_at is not None


def test_signature_covers_exact_bytes(client, world, run_jobs, receiver):
    publish(client, world["author"])
    run_jobs()
    req = receiver.for_path("shieldworks")[0]
    h = {k.lower(): v for k, v in req["headers"].items()}
    tampered = req["body"].replace(b"Acme Cyber", b"Evil Corp")
    assert not verify_signature(world["security"]["webhook_secret"], tampered,
                                h["x-agentnet-signature"], h["x-agentnet-timestamp"])


def _routed_notification(client, world, db):
    pid = publish(client, world["author"])
    routing.route_post(db, uuid.UUID(pid))
    return only_notification(db, world["security"]["id"])


def test_transient_failures_retry_then_fail_permanently(client, world, receiver, db):
    receiver.status = 500
    n = _routed_notification(client, world, db)
    for expected_attempts in (1, 2):
        with pytest.raises(DeliveryRetry):
            deliver_notification_job(str(n.id))
        db.expire_all()
        n = db.get(Notification, n.id)
        assert n.attempts == expected_attempts and n.delivery_status == "queued" and n.last_http_status == 500
    out = deliver_notification_job(str(n.id))                  # 3rd attempt == WEBHOOK_MAX_ATTEMPTS
    assert out["final"] is True
    db.expire_all()
    n = db.get(Notification, n.id)
    assert n.delivery_status == "failed" and n.attempts == 3


def test_recovers_when_receiver_comes_back(client, world, receiver, db):
    receiver.status = 503
    n = _routed_notification(client, world, db)
    with pytest.raises(DeliveryRetry):
        deliver_notification_job(str(n.id))
    receiver.status = 200
    assert deliver_notification_job(str(n.id))["delivered"] is True
    db.expire_all()
    n = db.get(Notification, n.id)
    assert n.delivery_status == "delivered" and n.attempts == 2


@pytest.mark.parametrize("status", [400, 401, 404, 302])
def test_non_retryable_status_fails_immediately(client, world, receiver, db, status):
    receiver.status = status        # includes 302: redirects are never followed
    n = _routed_notification(client, world, db)
    out = deliver_notification_job(str(n.id))
    assert out["final"] is True
    db.expire_all()
    assert db.get(Notification, n.id).delivery_status == "failed"
    assert len(receiver.for_path("shieldworks")) == 1          # no redirect follow-up / no retry


def test_connection_refused_is_retryable(client, world, db):
    n = _routed_notification(client, world, db)
    agent = db.get(Agent, uuid.UUID(world["security"]["id"]))
    agent.webhook_url = "http://127.0.0.1:1/unreachable"
    db.commit()
    with pytest.raises(DeliveryRetry):
        deliver_notification_job(str(n.id))
    db.expire_all()
    assert "ConnectError" in db.get(Notification, n.id).last_error


def test_ssrf_guard_rechecked_at_delivery(client, world, receiver, db, monkeypatch):
    from app.config import get_settings
    n = _routed_notification(client, world, db)
    monkeypatch.setattr(get_settings(), "allow_private_webhooks", False)   # e.g. DNS now points at localhost
    out = deliver_notification_job(str(n.id))
    assert out["final"] is True and "blocked" in out["error"]
    assert receiver.for_path("shieldworks") == []                           # nothing was sent
    db.expire_all()
    assert db.get(Notification, n.id).delivery_status == "failed"


def test_delivery_is_idempotent(client, world, receiver, db):
    n = _routed_notification(client, world, db)
    assert deliver_notification_job(str(n.id))["delivered"] is True
    assert deliver_notification_job(str(n.id)) == {"skipped": "already delivered"}
    assert len(receiver.for_path("shieldworks")) == 1


def test_inactive_recipient_not_delivered(client, world, receiver, db):
    n = _routed_notification(client, world, db)
    db.get(Agent, uuid.UUID(world["security"]["id"])).is_active = False
    db.commit()
    assert deliver_notification_job(str(n.id)) == {"skipped": "recipient inactive"}
    assert receiver.for_path("shieldworks") == []


def test_enqueue_delivery_configures_backoff(client, world, db):
    from app.services.queueing import enqueue_delivery, get_queue
    n = _routed_notification(client, world, db)
    job = get_queue().fetch_job(enqueue_delivery(n.id))
    assert job.retries_left == 2 and job.retry_intervals == [1, 1]       # WEBHOOK_MAX_ATTEMPTS=3, backoff "1,1"


def test_publish_survives_redis_outage(client, world, monkeypatch):
    from redis.exceptions import ConnectionError as RedisConnError
    import app.routers.posts as posts_router
    def boom(_):
        raise RedisConnError("down")
    monkeypatch.setattr(posts_router, "enqueue_route_post", boom)
    r = client.post("/api/v1/posts", headers=world["author"]["headers"], json={**SECURITY_POST, "publish": True})
    assert r.status_code == 201 and r.json()["routing_status"] == "failed"
    monkeypatch.undo()
    again = client.post(f"/api/v1/posts/{r.json()['id']}/reroute", headers=world["author"]["headers"])
    assert again.status_code == 200 and again.json()["routing_status"] == "pending"
    assert client.post(f"/api/v1/posts/{r.json()['id']}/reroute", headers=world["author"]["headers"]).status_code == 409
