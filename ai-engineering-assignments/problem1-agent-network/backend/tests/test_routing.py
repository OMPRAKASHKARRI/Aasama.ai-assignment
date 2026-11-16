"""Integration: SQL filter -> pgvector search -> rerank, against real Postgres/pgvector."""
import uuid

from app.models import Notification, Post
from app.services import routing
from app.services.reranking import LocalReranker, RerankError
from tests.conftest import SECURITY_POST


def publish(client, who, **over):
    r = client.post("/api/v1/posts", headers=who["headers"], json={**SECURITY_POST, "publish": True, **over})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def recipients(db, post_id):
    rows = db.query(Notification).filter(Notification.post_id == uuid.UUID(post_id)).all()
    return {str(n.agent_id): n for n in rows}


def test_only_relevant_agents_selected(client, world, db):
    pid = publish(client, world["author"])
    report, new_ids = routing.route_post(db, uuid.UUID(pid))
    got = recipients(db, pid)
    assert world["security"]["id"] in got                       # relevant -> notified
    assert world["bakery"]["id"] not in got                     # unrelated -> not notified
    assert world["freight"]["id"] not in got
    assert world["author"]["id"] not in got                     # never notify the author
    assert len(new_ids) == len(got)
    assert report["stage1_sql_candidates"] == 3                 # everyone except the author
    assert report["stage2_vector_shortlist"] >= report["stage3_selected"] >= 1
    assert got[world["security"]["id"]].rank == 1
    assert 0.2 <= got[world["security"]["id"]].rerank_score <= 1.0


def test_target_industries_sql_filter(client, world, db):
    pid = publish(client, world["author"], target_industries=["logistics"])
    report, _ = routing.route_post(db, uuid.UUID(pid))
    assert report["stage1_sql_candidates"] == 1                 # only the Logistics agent survives stage 1
    # the Logistics agent survives SQL filtering but is irrelevant to a security post -> dropped by stages 2/3
    assert recipients(db, pid) == {}
    assert world["security"]["id"] not in recipients(db, pid)   # relevant but filtered out by the SQL stage


def test_inactive_agents_excluded(client, world, db):
    from app.models import Agent
    db.get(Agent, uuid.UUID(world["security"]["id"])).is_active = False
    db.commit()
    pid = publish(client, world["author"])
    routing.route_post(db, uuid.UUID(pid))
    assert world["security"]["id"] not in recipients(db, pid)


def test_routing_is_idempotent(client, world, db):
    pid = publish(client, world["author"])
    routing.route_post(db, uuid.UUID(pid))
    first = set(recipients(db, pid))
    _, second_new = routing.route_post(db, uuid.UUID(pid))
    assert second_new == [] and set(recipients(db, pid)) == first


def test_draft_cannot_be_routed(client, world, db):
    pid = client.post("/api/v1/posts", headers=world["author"]["headers"], json=SECURITY_POST).json()["id"]
    try:
        routing.route_post(db, uuid.UUID(pid))
        raise AssertionError("expected RoutingError")
    except routing.RoutingError:
        pass


def test_top_n_cap(client, make_agent, db, monkeypatch):
    from app.config import get_settings
    author = make_agent("Author Inc", "Cybersecurity", "We publish cloud security research and tooling.")
    for i in range(5):
        make_agent(f"SecFan {i}", "Cybersecurity",
                   "We build cloud security zero-trust access threat detection and compliance automation tools.")
    monkeypatch.setattr(get_settings(), "rerank_top_n", 2)
    pid = publish(client, author)
    report, _ = routing.route_post(db, uuid.UUID(pid))
    assert report["stage3_selected"] == 2 and len(recipients(db, pid)) == 2


def test_reranker_failure_falls_back_to_local(client, world, db):
    class Broken:
        name = "broken"
        def score(self, post, candidates):
            raise RerankError("boom")
    pid = publish(client, world["author"])
    report, _ = routing.route_post(db, uuid.UUID(pid), reranker=Broken())
    assert report["reranker_fallback"] is True and report["reranker"] == LocalReranker.name
    assert world["security"]["id"] in recipients(db, pid)


def test_feedback_loop_prefers_agents_with_positive_history(client, make_agent, db):
    """Two agents with identical manifestos: the one with a 'relevant' history outranks the one marked 'not_relevant'."""
    manifesto = "We build cloud security zero-trust access threat detection and compliance automation tools."
    author = make_agent("Author Inc", "Cybersecurity", "We publish cloud security research and tooling.")
    liked = make_agent("Liked Co", "Cybersecurity", manifesto)
    disliked = make_agent("Disliked Co", "Cybersecurity", manifesto)

    # history: three earlier notifications with opposite feedback
    for i in range(3):
        old = publish(client, author, title=f"Earlier security note {i}")
        routing.route_post(db, uuid.UUID(old))
        recs = recipients(db, old)
        recs[liked["id"]].feedback = "relevant"
        recs[disliked["id"]].feedback = "not_relevant"
        db.commit()

    from app.services.routing import feedback_priors
    priors = feedback_priors(db, [uuid.UUID(liked["id"]), uuid.UUID(disliked["id"])])
    assert priors[uuid.UUID(liked["id"])] > 0.5 > priors[uuid.UUID(disliked["id"])]

    new = publish(client, author, title="Fresh zero-trust cloud security release")
    routing.route_post(db, uuid.UUID(new))
    got = recipients(db, new)
    assert got[liked["id"]].rerank_score > got[disliked["id"]].rerank_score
    assert got[liked["id"]].rank < got[disliked["id"]].rank


def test_routing_report_endpoint_and_async_pipeline(client, world, run_jobs, receiver):
    pid = publish(client, world["author"])
    assert client.get(f"/api/v1/posts/{pid}", headers=world["author"]["headers"]).json()["routing_status"] == "pending"
    run_jobs()   # real RQ worker: route job -> fan-out delivery jobs
    rep = client.get(f"/api/v1/posts/{pid}/routing", headers=world["author"]["headers"]).json()
    assert rep["routing_status"] == "routed" and rep["report"]["stage3_selected"] >= 1
    names = [r["company_name"] for r in rep["recipients"]]
    assert "ShieldWorks" in names and "Rise Bakery" not in names
    assert rep["engagement"]["delivered"] == rep["engagement"]["notified"]
