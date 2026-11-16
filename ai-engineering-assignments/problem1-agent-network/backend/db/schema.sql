
\restrict JwbvULEIY5Vq2L6rgwNLNw3A8djpaKfY8vNan1yZABdn1x480h86aRecFWXznoN

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';

SET default_tablespace = '';

SET default_table_access_method = heap;

CREATE TABLE public.agents (
    id uuid NOT NULL,
    company_name character varying(120) NOT NULL,
    industry character varying(80) NOT NULL,
    webhook_url text NOT NULL,
    manifesto text NOT NULL,
    embedding public.vector(384) NOT NULL,
    api_key_hash character varying(64) NOT NULL,
    webhook_secret character varying(128) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);

CREATE TABLE public.comments (
    id uuid NOT NULL,
    post_id uuid NOT NULL,
    author_id uuid NOT NULL,
    parent_id uuid,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

CREATE TABLE public.notifications (
    id uuid NOT NULL,
    post_id uuid NOT NULL,
    agent_id uuid NOT NULL,
    rank integer NOT NULL,
    similarity double precision NOT NULL,
    rerank_score double precision NOT NULL,
    delivery_status character varying(16) DEFAULT 'queued'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_http_status integer,
    last_error text,
    delivered_at timestamp with time zone,
    opened_at timestamp with time zone,
    feedback character varying(16),
    feedback_note text,
    feedback_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_notifications_delivery_status CHECK (((delivery_status)::text = ANY ((ARRAY['queued'::character varying, 'delivered'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_notifications_feedback CHECK (((feedback IS NULL) OR ((feedback)::text = ANY ((ARRAY['relevant'::character varying, 'not_relevant'::character varying])::text[]))))
);

CREATE TABLE public.posts (
    id uuid NOT NULL,
    author_id uuid NOT NULL,
    title character varying(200) NOT NULL,
    content text NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    target_industries jsonb DEFAULT '[]'::jsonb NOT NULL,
    status character varying(16) DEFAULT 'draft'::character varying NOT NULL,
    embedding public.vector(384) NOT NULL,
    routing_status character varying(16) DEFAULT 'not_started'::character varying NOT NULL,
    routing_report jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    published_at timestamp with time zone,
    CONSTRAINT ck_posts_routing_status CHECK (((routing_status)::text = ANY ((ARRAY['not_started'::character varying, 'pending'::character varying, 'routed'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT ck_posts_status CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'published'::character varying])::text[])))
);

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_api_key_hash_key UNIQUE (api_key_hash);

ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT comments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.posts
    ADD CONSTRAINT posts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT uq_notification_post_agent UNIQUE (post_id, agent_id);

CREATE INDEX ix_agents_embedding_hnsw ON public.agents USING hnsw (embedding public.vector_cosine_ops);

CREATE INDEX ix_agents_industry ON public.agents USING btree (industry);

CREATE INDEX ix_agents_industry_lower ON public.agents USING btree (lower((industry)::text));

CREATE INDEX ix_comments_post_id ON public.comments USING btree (post_id);

CREATE INDEX ix_notifications_agent_id ON public.notifications USING btree (agent_id);

CREATE INDEX ix_notifications_delivery_status ON public.notifications USING btree (delivery_status);

CREATE INDEX ix_posts_author_id ON public.posts USING btree (author_id);

CREATE INDEX ix_posts_published_at ON public.posts USING btree (published_at);

CREATE INDEX ix_posts_status ON public.posts USING btree (status);

CREATE INDEX ix_posts_tags_gin ON public.posts USING gin (tags);

CREATE UNIQUE INDEX uq_agents_company_name_lower ON public.agents USING btree (lower((company_name)::text));

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT comments_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.agents(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT comments_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.comments(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT comments_post_id_fkey FOREIGN KEY (post_id) REFERENCES public.posts(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_post_id_fkey FOREIGN KEY (post_id) REFERENCES public.posts(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.posts
    ADD CONSTRAINT posts_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.agents(id) ON DELETE CASCADE;

\unrestrict JwbvULEIY5Vq2L6rgwNLNw3A8djpaKfY8vNan1yZABdn1x480h86aRecFWXznoN

