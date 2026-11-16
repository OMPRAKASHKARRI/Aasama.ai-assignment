"""initial schema: agents, posts, comments, notifications + pgvector

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql as pg

from app.config import get_settings

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

DIM = get_settings().embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "agents",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(120), nullable=False),
        sa.Column("industry", sa.String(80), nullable=False),
        sa.Column("webhook_url", sa.Text, nullable=False),
        sa.Column("manifesto", sa.Text, nullable=False),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("api_key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("webhook_secret", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agents_industry", "agents", ["industry"])
    op.execute("CREATE UNIQUE INDEX uq_agents_company_name_lower ON agents (lower(company_name))")
    op.execute("CREATE INDEX ix_agents_industry_lower ON agents (lower(industry))")
    # Approximate nearest-neighbour index for stage-2 cosine search.
    op.execute("CREATE INDEX ix_agents_embedding_hnsw ON agents USING hnsw (embedding vector_cosine_ops)")

    op.create_table(
        "posts",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("author_id", pg.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("tags", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("target_industries", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("embedding", Vector(DIM), nullable=False),
        sa.Column("routing_status", sa.String(16), nullable=False, server_default="not_started"),
        sa.Column("routing_report", pg.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft','published')", name="ck_posts_status"),
        sa.CheckConstraint("routing_status IN ('not_started','pending','routed','failed')", name="ck_posts_routing_status"),
    )
    op.create_index("ix_posts_author_id", "posts", ["author_id"])
    op.create_index("ix_posts_status", "posts", ["status"])
    op.create_index("ix_posts_published_at", "posts", ["published_at"])
    op.execute("CREATE INDEX ix_posts_tags_gin ON posts USING gin (tags)")

    op.create_table(
        "comments",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("post_id", pg.UUID(as_uuid=True), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", pg.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", pg.UUID(as_uuid=True), sa.ForeignKey("comments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_comments_post_id", "comments", ["post_id"])

    op.create_table(
        "notifications",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("post_id", pg.UUID(as_uuid=True), sa.ForeignKey("posts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", pg.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("similarity", sa.Float, nullable=False),
        sa.Column("rerank_score", sa.Float, nullable=False),
        sa.Column("delivery_status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_http_status", sa.Integer, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", sa.String(16), nullable=True),
        sa.Column("feedback_note", sa.Text, nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("post_id", "agent_id", name="uq_notification_post_agent"),
        sa.CheckConstraint("delivery_status IN ('queued','delivered','failed')", name="ck_notifications_delivery_status"),
        sa.CheckConstraint("feedback IS NULL OR feedback IN ('relevant','not_relevant')", name="ck_notifications_feedback"),
    )
    op.create_index("ix_notifications_agent_id", "notifications", ["agent_id"])
    op.create_index("ix_notifications_delivery_status", "notifications", ["delivery_status"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("comments")
    op.drop_table("posts")
    op.drop_table("agents")
