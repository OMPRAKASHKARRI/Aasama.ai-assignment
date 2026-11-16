"""Three-stage semantic relevance routing.

Stage 1  SQL filter      active agents, not the author, not already notified, optional industry targeting.
Stage 2  Vector search   pgvector cosine distance (HNSW) restricted to stage 1, top-K above a similarity floor.
Stage 3  Rerank          provider scores the shortlist; feedback history nudges the score; top-N above a floor.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import case, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Agent, Notification, Post
from app.services.reranking import (
    Candidate, LocalReranker, PostQuery, RerankError, Reranker, get_reranker,
)

log = logging.getLogger(__name__)


class RoutingError(RuntimeError):
    pass


def stage1_filter(post: Post):
    """Return the SQL ``SELECT agents.id`` for agents that are even eligible to be notified."""
    already = exists().where(Notification.post_id == post.id, Notification.agent_id == Agent.id)
    q = select(Agent.id).where(Agent.is_active.is_(True), Agent.id != post.author_id, ~already)
    targets = [t.lower() for t in (post.target_industries or [])]
    if targets:
        q = q.where(func.lower(Agent.industry).in_(targets))
    return q


def stage2_vector_search(db: Session, post: Post, eligible, settings: Settings) -> list[tuple]:
    distance = Agent.embedding.cosine_distance(post.embedding)
    rows = db.execute(
        select(Agent.id, Agent.industry, Agent.manifesto, (1 - distance).label("similarity"))
        .where(Agent.id.in_(eligible))
        .order_by(distance)
        .limit(settings.vector_top_k)
    ).all()
    return [r for r in rows if r.similarity >= settings.min_similarity]


def feedback_priors(db: Session, agent_ids: list[uuid.UUID]) -> dict[uuid.UUID, float]:
    """Laplace-smoothed share of 'relevant' feedback per agent (0.5 when no feedback yet)."""
    if not agent_ids:
        return {}
    rows = db.execute(
        select(
            Notification.agent_id,
            func.sum(case((Notification.feedback == "relevant", 1), else_=0)),
            func.sum(case((Notification.feedback == "not_relevant", 1), else_=0)),
        ).where(Notification.agent_id.in_(agent_ids)).group_by(Notification.agent_id)
    ).all()
    priors = {a: 0.5 for a in agent_ids}
    for agent_id, pos, neg in rows:
        pos, neg = int(pos or 0), int(neg or 0)
        priors[agent_id] = (pos + 1) / (pos + neg + 2)
    return priors


def stage3_rerank(db: Session, post: Post, shortlist: list[tuple], settings: Settings,
                  reranker: Reranker | None = None) -> tuple[list[tuple[tuple, float]], str, bool]:
    reranker = reranker or get_reranker()
    query = PostQuery(post.title, post.content, list(post.tags or []), post.author.industry)
    candidates = [Candidate(str(r.id), r.industry, r.manifesto, float(r.similarity)) for r in shortlist]
    used, fell_back = reranker.name, False
    try:
        scores = reranker.score(query, candidates)
    except RerankError as exc:
        log.warning("reranker %s failed (%s); falling back to local scorer", reranker.name, exc)
        used, fell_back = LocalReranker.name, True
        scores = LocalReranker().score(query, candidates)

    priors = feedback_priors(db, [r.id for r in shortlist])
    final = [s * (0.85 + 0.30 * priors[r.id]) for s, r in zip(scores, shortlist)]
    ranked = sorted(zip(shortlist, final), key=lambda p: p[1], reverse=True)
    kept = [(r, min(1.0, s)) for r, s in ranked if s >= settings.min_rerank_score][: settings.rerank_top_n]
    return kept, used, fell_back


def route_post(db: Session, post_id: uuid.UUID, settings: Settings | None = None,
               reranker: Reranker | None = None) -> tuple[dict, list[uuid.UUID]]:
    """Run all three stages, persist notifications + a routing report, return (report, new_notification_ids)."""
    settings = settings or get_settings()
    post = db.get(Post, post_id)
    if post is None:
        raise RoutingError(f"post {post_id} not found")
    if post.status != "published":
        raise RoutingError("only published posts can be routed")

    eligible = stage1_filter(post)
    stage1_count = db.scalar(select(func.count()).select_from(eligible.subquery())) or 0
    shortlist = stage2_vector_search(db, post, eligible, settings) if stage1_count else []
    selected, reranker_name, fell_back = (
        stage3_rerank(db, post, shortlist, settings, reranker) if shortlist else ([], "n/a", False)
    )

    new_ids: list[uuid.UUID] = []
    for rank, (row, score) in enumerate(selected, start=1):
        nid = uuid.uuid4()
        inserted = db.execute(
            pg_insert(Notification).values(
                id=nid, post_id=post.id, agent_id=row.id, rank=rank, similarity=float(row.similarity),
                rerank_score=float(score), delivery_status="queued", attempts=0,
                created_at=datetime.now(timezone.utc),
            ).on_conflict_do_nothing(constraint="uq_notification_post_agent").returning(Notification.id)
        ).scalar_one_or_none()
        if inserted:
            new_ids.append(inserted)

    report = {
        "stage1_sql_candidates": stage1_count,
        "stage2_vector_shortlist": len(shortlist),
        "stage3_selected": len(selected),
        "notified_agent_ids": [str(r.id) for r, _ in selected],
        "reranker": reranker_name,
        "reranker_fallback": fell_back,
        "thresholds": {"vector_top_k": settings.vector_top_k, "min_similarity": settings.min_similarity,
                       "rerank_top_n": settings.rerank_top_n, "min_rerank_score": settings.min_rerank_score},
        "routed_at": datetime.now(timezone.utc).isoformat(),
    }
    post.routing_status = "routed"
    post.routing_report = report
    db.commit()
    return report, new_ids
