import json

import httpx
import pytest

from app.services.embeddings import (
    EmbeddingError, HashingEmbedder, OllamaEmbedder, OpenAIEmbedder, tokenize,
)
from app.services.reranking import (
    Candidate, HttpReranker, LocalReranker, OllamaReranker, PostQuery, RerankError,
)


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


class TestHashingEmbedder:
    e = HashingEmbedder(384)

    def test_dim_and_unit_norm_and_determinism(self):
        v1, v2 = self.e.embed(["zero trust cloud security"] * 2)
        assert len(v1) == 384 and abs(cos(v1, v1) - 1) < 1e-9 and v1 == v2

    def test_related_texts_closer_than_unrelated(self):
        q, rel, unrel = self.e.embed([
            "cloud security zero-trust threat detection",
            "We build zero-trust cloud security and threat detection tools",
            "Artisan bakery sourdough pastry flour suppliers"])
        assert cos(q, rel) > 0.4 > cos(q, unrel) + 0.3

    def test_stopword_only_text_still_embeds(self):
        v = self.e.embed(["the and of"])[0]
        assert len(v) == 384 and abs(cos(v, v) - 1) < 1e-9

    def test_tokenize_drops_stopwords_and_stems(self):
        assert tokenize("The delivering of shipments") == ["deliver", "ship"]
        assert tokenize("shipment") == tokenize("shipments") == tokenize("shipping")  # consistent stems


def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestRemoteEmbedders:
    def test_ollama_parses_and_normalises(self):
        def handler(req):
            assert req.url.path == "/api/embed" and json.loads(req.content)["model"] == "nomic-embed-text"
            return httpx.Response(200, json={"embeddings": [[3.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]})
        e = OllamaEmbedder("http://x", "nomic-embed-text", 8, 5, client=_mock(handler))
        v = e.embed(["hi"])[0]
        assert v[:2] == pytest.approx([0.6, 0.8])

    def test_ollama_dimension_mismatch_is_an_error(self):
        e = OllamaEmbedder("http://x", "m", 8, 5, client=_mock(lambda r: httpx.Response(200, json={"embeddings": [[1.0, 2.0]]})))
        with pytest.raises(EmbeddingError, match="EMBEDDING_DIM"):
            e.embed(["hi"])

    def test_ollama_http_error(self):
        e = OllamaEmbedder("http://x", "m", 8, 5, client=_mock(lambda r: httpx.Response(500)))
        with pytest.raises(EmbeddingError):
            e.embed(["hi"])

    def test_openai_orders_by_index_and_sends_auth(self):
        def handler(req):
            assert req.headers["authorization"] == "Bearer sk-test"
            return httpx.Response(200, json={"data": [
                {"index": 1, "embedding": [0, 1, 0, 0, 0, 0, 0, 0]},
                {"index": 0, "embedding": [1, 0, 0, 0, 0, 0, 0, 0]}]})
        e = OpenAIEmbedder("http://x/v1", "m", "sk-test", 8, 5, client=_mock(handler))
        a, b = e.embed(["a", "b"])
        assert a[0] == 1.0 and b[1] == 1.0


POST = PostQuery("Zero-trust cloud security", "Reference design for identity-aware access and threat detection",
                 ["cloud-security"], "Cybersecurity")
CANDS = [
    Candidate("sec", "Cybersecurity", "We build cloud security, zero-trust access and threat detection.", 0.6),
    Candidate("bake", "Food", "Artisan bakery interested in flour and pastry ovens.", 0.05),
]


class TestRerankers:
    def test_local_ranks_relevant_first_and_scores_bounded(self):
        s = LocalReranker().score(POST, CANDS)
        assert s[0] > s[1] + 0.3 and all(0 <= x <= 1 for x in s)

    def test_local_empty(self):
        assert LocalReranker().score(POST, []) == []

    def test_ollama_parses_json_scores(self):
        def handler(req):
            body = json.loads(req.content)
            assert "untrusted" in body["messages"][0]["content"] and body["stream"] is False
            return httpx.Response(200, json={"message": {"content": json.dumps(
                {"scores": [{"id": 1, "score": 0.1}, {"id": 0, "score": 0.9}]})}})
        r = OllamaReranker("http://x", "m", 5, client=_mock(handler))
        assert r.score(POST, CANDS) == [0.9, 0.1]

    def test_ollama_incomplete_or_garbage_raises(self):
        bad = _mock(lambda r: httpx.Response(200, json={"message": {"content": "not json"}}))
        with pytest.raises(RerankError):
            OllamaReranker("http://x", "m", 5, client=bad).score(POST, CANDS)
        partial = _mock(lambda r: httpx.Response(200, json={"message": {"content": '{"scores":[{"id":0,"score":1}]}'}}))
        with pytest.raises(RerankError):
            OllamaReranker("http://x", "m", 5, client=partial).score(POST, CANDS)

    def test_http_reranker_cohere_style(self):
        def handler(req):
            assert req.url.path == "/rerank" and len(json.loads(req.content)["documents"]) == 2
            return httpx.Response(200, json={"results": [
                {"index": 1, "relevance_score": 0.2}, {"index": 0, "relevance_score": 1.7}]})
        r = HttpReranker("http://x", "rerank-v3", "k", 5, client=_mock(handler))
        assert r.score(POST, CANDS) == [1.0, 0.2]   # clamped to [0, 1]

    def test_http_reranker_failure_raises(self):
        with pytest.raises(RerankError):
            HttpReranker("http://x", "m", "", 5, client=_mock(lambda r: httpx.Response(503))).score(POST, CANDS)
