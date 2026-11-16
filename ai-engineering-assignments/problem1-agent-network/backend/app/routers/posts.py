from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import rate_limited_agent
from app.models import Agent, Comment, Notification, Post
from app.routers._common import screen_untrusted
from app.schemas import CommentCreate, CommentOut, PostCreate, PostOut, RecipientReport, RoutingReport
from app.services.embeddings import embed_one
from app.services.queueing import enqueue_route_post

log = logging.getLogger(__name__)
router = APIRouter(prefix="/posts", tags=["posts"])


def _visible_post(db: Session, post_id: uuid.UUID, agent: Agent) -> Post:
    """Drafts are visible to their author only; everything else about a draft is a 404 (no existence leak)."""
    post = db.get(Post, post_id)
    if post is None or (post.status != "published" and post.author_id != agent.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "post not found")
    return post


def _own_post(db: Session, post_id: uuid.UUID, agent: Agent) -> Post:
    post = db.get(Post, post_id)
    if post is None or post.author_id != agent.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "post not found")
    return post


def _start_routing(db: Session, post: Post) -> None:
    post.routing_status = "pending"
    db.commit()
    try:
        enqueue_route_post(post.id)
    except RedisError as exc:
        log.error("could not enqueue routing for %s: %s", post.id, exc)
        post.routing_status = "failed"
        db.commit()


def _publish(db: Session, post: Post) -> None:
    post.status = "published"
    post.published_at = datetime.now(timezone.utc)
    _start_routing(db, post)


@router.post("", response_model=PostOut, status_code=status.HTTP_201_CREATED, summary="Create a post (draft or publish)")
def create_post(body: PostCreate, agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> Post:
    s = get_settings()
    if len(body.content) > s.max_post_chars:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "content too long")
    screen_untrusted(title=body.title, content=body.content, tags=" ".join(body.tags))
    post = Post(
        author_id=agent.id, title=body.title, content=body.content, tags=body.tags,
        target_industries=body.target_industries, status="draft",
        embedding=embed_one(f"{body.title}\n{body.content}\n{' '.join(body.tags)}"),
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    if body.publish:
        _publish(db, post)
    return post


@router.get("", response_model=list[PostOut], summary="List published posts (optionally include your own drafts)")
def list_posts(
    tag: str | None = None, industry: str | None = None, mine: bool = False,
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
    agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db),
) -> list[Post]:
    q = select(Post).order_by(func.coalesce(Post.published_at, Post.created_at).desc()).limit(limit).offset(offset)
    if mine:
        q = q.where(Post.author_id == agent.id)
    else:
        q = q.where(Post.status == "published")
    if tag:
        q = q.where(Post.tags.contains([tag.lower()]))
    if industry:
        q = q.join(Agent, Agent.id == Post.author_id).where(func.lower(Agent.industry) == industry.lower())
    return list(db.scalars(q).unique())


@router.get("/{post_id}", response_model=PostOut, summary="Retrieve a post")
def get_post(post_id: uuid.UUID, agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> Post:
    return _visible_post(db, post_id, agent)


@router.post("/{post_id}/publish", response_model=PostOut, summary="Publish a draft and start routing")
def publish_post(post_id: uuid.UUID, agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> Post:
    post = _own_post(db, post_id, agent)
    if post.status == "published":
        return post  # idempotent
    _publish(db, post)
    return post


@router.post("/{post_id}/reroute", response_model=PostOut,
             summary="Re-queue routing for a published post whose routing failed")
def reroute_post(post_id: uuid.UUID, agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> Post:
    post = _own_post(db, post_id, agent)
    if post.status != "published":
        raise HTTPException(status.HTTP_409_CONFLICT, "post is not published")
    if post.routing_status not in ("failed", "not_started"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"routing is already {post.routing_status}")
    _start_routing(db, post)
    return post


@router.get("/{post_id}/routing", response_model=RoutingReport, summary="Routing report and engagement (author only)")
def routing_report(post_id: uuid.UUID, agent: Agent = Depends(rate_limited_agent),
                   db: Session = Depends(get_db)) -> RoutingReport:
    post = _own_post(db, post_id, agent)
    rows = db.execute(
        select(Notification, Agent.company_name).join(Agent, Agent.id == Notification.agent_id)
        .where(Notification.post_id == post.id).order_by(Notification.rank)
    ).unique().all()
    recipients = [
        RecipientReport(agent_id=n.agent_id, company_name=name, rank=n.rank, similarity=n.similarity,
                        rerank_score=n.rerank_score, delivery_status=n.delivery_status, attempts=n.attempts,
                        opened=n.opened_at is not None, feedback=n.feedback)
        for n, name in rows
    ]
    engagement = {
        "notified": len(rows),
        "delivered": sum(r.delivery_status == "delivered" for r in recipients),
        "failed": sum(r.delivery_status == "failed" for r in recipients),
        "opened": sum(r.opened for r in recipients),
        "relevant": sum(r.feedback == "relevant" for r in recipients),
        "not_relevant": sum(r.feedback == "not_relevant" for r in recipients),
    }
    return RoutingReport(post_id=post.id, routing_status=post.routing_status, report=post.routing_report,
                         recipients=recipients, engagement=engagement)


@router.post("/{post_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED,
             summary="Comment on a published post")
def add_comment(post_id: uuid.UUID, body: CommentCreate, agent: Agent = Depends(rate_limited_agent),
                db: Session = Depends(get_db)) -> Comment:
    post = _visible_post(db, post_id, agent)
    if post.status != "published":
        raise HTTPException(status.HTTP_409_CONFLICT, "cannot comment on an unpublished post")
    if len(body.content) > get_settings().max_comment_chars:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "comment too long")
    screen_untrusted(content=body.content)
    if body.parent_id is not None:
        parent = db.get(Comment, body.parent_id)
        if parent is None or parent.post_id != post.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "parent comment not found on this post")
    comment = Comment(post_id=post.id, author_id=agent.id, parent_id=body.parent_id, content=body.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/{post_id}/comments", response_model=list[CommentOut], summary="List comments on a post")
def list_comments(post_id: uuid.UUID, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0),
                  agent: Agent = Depends(rate_limited_agent), db: Session = Depends(get_db)) -> list[Comment]:
    post = _visible_post(db, post_id, agent)
    q = select(Comment).where(Comment.post_id == post.id).order_by(Comment.created_at).limit(limit).offset(offset)
    return list(db.scalars(q).unique())
