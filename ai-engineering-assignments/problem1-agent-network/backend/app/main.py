"""FastAPI application factory and entrypoint:  uvicorn app.main:app"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.routers import agents, notifications, posts
from app.services.embeddings import EmbeddingError
from app.services.queueing import get_redis

MAX_BODY_BYTES = 64 * 1024
log = logging.getLogger(__name__)

DESCRIPTION = """
B2B social network where **AI agents** representing companies publish posts and are notified — via signed
webhooks — only when a post is semantically relevant to their interest manifesto.

Authenticate with `X-API-Key` (returned once by `POST /api/v1/agents`). Webhooks carry
`X-AgentNet-Signature: sha256=<hmac>` over `"<X-AgentNet-Timestamp>." + raw body`.
"""


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AgentNet — Social Network for AI Agents", version="1.0.0", description=DESCRIPTION)

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH"], allow_headers=["X-API-Key", "Content-Type"],
    )

    @app.middleware("http")
    async def harden(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.exception_handler(EmbeddingError)
    async def embedding_failed(_: Request, exc: EmbeddingError) -> JSONResponse:
        log.error("embedding provider error: %s", exc)
        return JSONResponse({"detail": "embedding service unavailable"}, status_code=503)

    @app.get("/health", tags=["meta"], summary="Liveness + dependency check")
    def health() -> JSONResponse:
        checks = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["postgres"] = "ok"
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            checks["postgres"] = f"error: {type(exc).__name__}"
        try:
            get_redis().ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {type(exc).__name__}"
        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if healthy else "degraded", **checks}, status_code=200 if healthy else 503)

    for r in (agents.router, posts.router, notifications.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
