"""Embedding providers.

``local``   Dependency-free feature-hashing embedder (unigrams + bigrams, signed hashing, sublinear TF,
            L2-normalised). It is a *lexical* model: it works offline and deterministically, but it does
            not understand synonyms. Use it for development/CI or air-gapped installs.
``ollama``  Calls a local Ollama server (``/api/embed``), e.g. ``nomic-embed-text`` (768-d).
``openai``  Calls any OpenAI-compatible ``/embeddings`` endpoint.

For real semantic matching in production use ``ollama`` or ``openai`` and set ``EMBEDDING_DIM`` to
the model's output size *before* running migrations (the pgvector column dimension is fixed).
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.security import sanitize_text


class EmbeddingError(RuntimeError):
    pass


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-\+\.#]*[a-z0-9]|[a-z0-9]")
_STOP = frozenset(
    "a an the and or but if of to in on at by for with from as is are was were be been being this that these "
    "those it its we our us you your they their i he she his her not no yes do does did done have has had can "
    "could should would will shall may might must about into over under more most than then so such very also "
    "just per via any all each both few other some how what when where which who why".split()
)
_SUFFIXES = ("ization", "ations", "ation", "ingly", "ments", "ment", "ities", "ness", "ings", "ing", "ies", "ied",
             "ers", "est", "ed", "es", "er", "ly", "s")


def _stem(tok: str) -> str:
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            stem = tok[: -len(suf)]
            # undo consonant doubling introduced by inflection: shipp(ing) -> ship, runn(ing) -> run
            if len(stem) >= 4 and stem[-1] == stem[-2] and stem[-1] not in "aeiouls":
                stem = stem[:-1]
            return stem
    return tok


def tokenize(text: str) -> list[str]:
    """Lowercase, split, drop stop-words, light suffix stemming. Shared with the local reranker."""
    return [_stem(t) for t in _TOKEN.findall(sanitize_text(text).lower()) if t not in _STOP]


class HashingEmbedder:
    name = "local-hashing"

    def __init__(self, dim: int):
        self.dim = dim

    def _slot(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dim, 1.0 if (value >> 63) & 1 else -1.0

    def _embed_one(self, text: str) -> list[float]:
        tokens = tokenize(text)
        counts: dict[str, float] = {}
        for tok in tokens:
            counts[tok] = counts.get(tok, 0.0) + 1.0
        for a, b in zip(tokens, tokens[1:]):
            key = f"{a}_{b}"
            counts[key] = counts.get(key, 0.0) + 0.6
        vec = [0.0] * self.dim
        for feat, tf in counts.items():
            idx, sign = self._slot(feat)
            vec[idx] += sign * (1.0 + math.log(tf)) if tf >= 1 else sign * tf
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            # No usable tokens (e.g. only stop-words): fall back to a stable pseudo-direction on raw text.
            idx, sign = self._slot("__empty__:" + text)
            vec[idx] = sign
            return vec
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


def _check_dim(vectors: list[list[float]], dim: int, who: str) -> list[list[float]]:
    for v in vectors:
        if len(v) != dim:
            raise EmbeddingError(
                f"{who} returned {len(v)}-d vectors but EMBEDDING_DIM={dim}; fix the setting and re-run migrations"
            )
    return vectors


def _normalise(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, dim: int, timeout: float, client: httpx.Client | None = None):
        self.name = f"ollama:{model}"
        self.dim = dim
        self._url = base_url.rstrip("/") + "/api/embed"
        self._model = model
        self._client = client or httpx.Client(timeout=timeout)

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = self._client.post(self._url, json={"model": self._model, "input": texts})
            resp.raise_for_status()
            data = resp.json()
            vectors = data["embeddings"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc
        return _check_dim([_normalise(v) for v in vectors], self.dim, self.name)


class OpenAIEmbedder:
    def __init__(self, base_url: str, model: str, api_key: str, dim: int, timeout: float,
                 client: httpx.Client | None = None):
        self.name = f"openai:{model}"
        self.dim = dim
        self._url = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.Client(timeout=timeout)

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload: dict = {"model": self._model, "input": texts}
        try:
            resp = self._client.post(self._url, json=payload, headers=self._headers)
            resp.raise_for_status()
            rows = sorted(resp.json()["data"], key=lambda r: r["index"])
            vectors = [r["embedding"] for r in rows]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise EmbeddingError(f"OpenAI-compatible embedding request failed: {exc}") from exc
        return _check_dim([_normalise(v) for v in vectors], self.dim, self.name)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "local":
        return HashingEmbedder(settings.embedding_dim)
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(settings.embedding_base_url, settings.embedding_model,
                              settings.embedding_dim, settings.embedding_timeout_seconds)
    return OpenAIEmbedder(settings.embedding_base_url, settings.embedding_model, settings.embedding_api_key,
                          settings.embedding_dim, settings.embedding_timeout_seconds)


@lru_cache
def get_embedder() -> Embedder:
    return build_embedder(get_settings())


def embed_one(text: str) -> list[float]:
    return get_embedder().embed([text])[0]
