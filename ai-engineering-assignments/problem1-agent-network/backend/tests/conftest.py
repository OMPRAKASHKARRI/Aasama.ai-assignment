"""Test harness: real PostgreSQL+pgvector (schema built by Alembic) and real Redis/RQ.

Requires the services from .env.example; uses separate resources (DB ``agentnet_test``, Redis db 15).
"""
from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://agentnet:agentnet@localhost:5432/agentnet_test"),
    "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15"),
    "QUEUE_NAME": "agentnet-test",
    "EMBEDDING_PROVIDER": "local", "EMBEDDING_DIM": "384", "RERANKER_PROVIDER": "local",
    "ALLOW_PRIVATE_WEBHOOKS": "true",
    "REGISTER_RATE_LIMIT_PER_HOUR": "100000", "RATE_LIMIT_PER_MINUTE": "100000",
    "WEBHOOK_MAX_ATTEMPTS": "3", "WEBHOOK_BACKOFF_SECONDS": "1,1",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from rq import SimpleWorker  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import get_engine, get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.scripts.init_db import main as migrate  # noqa: E402
from app.services.queueing import get_queue, get_redis  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database():
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    migrate()  # the real Alembic migration, including the pgvector extension and HNSW index
    yield


@pytest.fixture(autouse=True)
def _clean():
    get_redis().flushdb()
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE notifications, comments, posts, agents RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture()
def run_jobs():
    """Drain the RQ queue synchronously with a real worker."""
    def _run() -> None:
        SimpleWorker([get_queue()], connection=get_redis()).work(burst=True)
    return _run


class Receiver:
    """A real HTTP server that records webhook calls and replies with a configurable status."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.status = 200
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *_: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.port}/{name}"

    def for_path(self, name: str) -> list[dict]:
        return [r for r in self.requests if r["path"] == f"/{name}"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def receiver():
    r = Receiver()
    yield r
    r.close()


@pytest.fixture()
def make_agent(client, receiver):
    def _make(name: str, industry: str, manifesto: str, hook: str | None = None) -> dict:
        resp = client.post("/api/v1/agents", json={
            "company_name": name, "industry": industry, "manifesto": manifesto,
            "webhook_url": receiver.url(hook or name.lower().replace(" ", "-")),
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        data["headers"] = {"X-API-Key": data["api_key"]}
        return data
    return _make


SECURITY_MANIFESTO = ("We build cloud security products: zero-trust access, threat detection, vulnerability "
                      "management and compliance automation for regulated industries.")
BAKERY_MANIFESTO = ("Artisan bakery chain interested in sourdough starters, flour suppliers, pastry ovens and "
                    "retail shop fit-outs for our cafes.")
FREIGHT_MANIFESTO = ("Freight logistics company interested in fleet telematics, warehouse automation, shipment "
                     "tracking and last-mile delivery optimisation.")


@pytest.fixture()
def world(make_agent):
    """Three agents with clearly different interests plus an author."""
    return {
        "author": make_agent("Acme Cyber", "Cybersecurity", SECURITY_MANIFESTO + " We also publish research."),
        "security": make_agent("ShieldWorks", "Cybersecurity", SECURITY_MANIFESTO),
        "bakery": make_agent("Rise Bakery", "Food", BAKERY_MANIFESTO),
        "freight": make_agent("MoveIt Freight", "Logistics", FREIGHT_MANIFESTO),
    }


SECURITY_POST = {
    "title": "Zero-trust architecture for cloud workloads",
    "content": "We are sharing a zero-trust cloud security reference design covering identity-aware access, "
               "threat detection and automated compliance checks for regulated industries.",
    "tags": ["zero-trust", "cloud-security"],
}

