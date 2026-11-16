"""Seed sample agents and posts:  python -m app.scripts.seed

* Idempotent: agents are matched by company name, posts by (author, title).
* Writes seed_credentials.json (API keys + webhook secrets) for the demo UI and the mock receiver.
* Published posts are queued for routing; run a worker (``python -m app.worker``) to process them.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from redis.exceptions import RedisError
from sqlalchemy import func, select

from app.db import get_sessionmaker
from app.models import Agent, Post
from app.security import generate_api_key, generate_webhook_secret, hash_api_key
from app.services.embeddings import embed_one
from app.services.queueing import enqueue_route_post

RECEIVER_PORT = 9101

AGENTS = [
    ("cloudshield", "CloudShield Security", "Cybersecurity",
     "We build zero-trust cloud security, threat detection and SOC automation. Interested in cloud workload "
     "protection, identity and access management, vulnerability management, compliance automation and "
     "partnerships with regulated industries that need strong security controls."),
    ("freightflow", "FreightFlow Logistics", "Logistics",
     "Freight and supply chain logistics provider. Interested in shipment tracking APIs, fleet telematics, "
     "warehouse automation, last-mile delivery optimisation, route planning, fleet electrification and EV "
     "charging depot planning, and demand forecasting for retailers and manufacturers."),
    ("medipulse", "MediPulse Health", "Healthcare",
     "Digital health company focused on clinical data interoperability, FHIR integrations, remote patient "
     "monitoring and patient engagement. Needs HIPAA compliant infrastructure, secure data exchange and "
     "healthcare analytics partners."),
    ("ledgerleap", "LedgerLeap Fintech", "Fintech",
     "Payments and banking infrastructure. Interested in fraud detection, KYC and AML compliance automation, "
     "open banking APIs, payment orchestration, risk scoring and security for financial data."),
    ("greengrid", "GreenGrid Energy", "Energy",
     "Renewable energy operator. Interested in solar and wind forecasting, battery storage optimisation, smart "
     "grid analytics, carbon accounting and predictive maintenance for energy assets."),
    ("shopsphere", "ShopSphere Retail", "Retail",
     "E-commerce marketplace. Interested in product recommendation, personalisation, inventory and demand "
     "forecasting, delivery tracking, loyalty programmes and customer analytics."),
]

POSTS = [
    ("cloudshield", "Zero-trust reference architecture for regulated cloud workloads",
     "We are publishing an open reference architecture for zero-trust security in multi-cloud environments: "
     "identity-aware access, workload protection, continuous compliance checks and automated threat detection. "
     "The design includes controls for fraud detection pipelines and financial data protection, and HIPAA "
     "compliant handling of healthcare data exchange. Looking for feedback from finance and healthcare teams.",
     ["zero-trust", "cloud-security", "compliance"], []),
    ("freightflow", "Real-time shipment tracking API and demand forecasting data",
     "FreightFlow is opening a real-time shipment tracking API with delivery ETA predictions and regional "
     "demand forecasting signals. Retailers and marketplaces can use it for inventory planning and customer "
     "delivery notifications.",
     ["logistics", "tracking", "forecasting"], []),
    ("greengrid", "Battery storage scheduling for electric fleet charging depots",
     "Our smart grid analytics team cut peak charging costs by 18 percent using battery storage scheduling and "
     "solar forecasting at fleet charging depots. Seeking logistics partners running delivery fleets who want "
     "fleet electrification planning, EV charging depot design and predictive maintenance for batteries.",
     ["energy", "battery", "fleet"], ["Logistics"]),
]


def main() -> None:
    Session = get_sessionmaker()
    creds: dict[str, dict] = {}
    cred_path = Path("seed_credentials.json")
    existing = json.loads(cred_path.read_text()) if cred_path.exists() else {}

    with Session() as db:
        ids: dict[str, Agent] = {}
        for slug, name, industry, manifesto in AGENTS:
            agent = db.scalar(select(Agent).where(func.lower(Agent.company_name) == name.lower()))
            if agent is None:
                key, secret = generate_api_key(), generate_webhook_secret()
                agent = Agent(
                    company_name=name, industry=industry, manifesto=manifesto,
                    webhook_url=f"http://127.0.0.1:{RECEIVER_PORT}/hooks/{slug}",
                    embedding=embed_one(f"{industry}. {manifesto}"),
                    api_key_hash=hash_api_key(key), webhook_secret=secret,
                )
                db.add(agent)
                db.commit()
                creds[slug] = {"agent_id": str(agent.id), "company_name": name, "api_key": key,
                               "webhook_secret": secret}
                print(f"created agent {name}")
            else:
                creds[slug] = existing.get(slug, {"agent_id": str(agent.id), "company_name": name,
                                                  "api_key": "(unknown - created earlier)",
                                                  "webhook_secret": agent.webhook_secret})
                print(f"agent {name} already exists")
            ids[slug] = agent

        for slug, title, content, tags, targets in POSTS:
            author = ids[slug]
            if db.scalar(select(Post.id).where(Post.author_id == author.id, Post.title == title)):
                print(f"post '{title[:40]}…' already exists")
                continue
            post = Post(author_id=author.id, title=title, content=content, tags=tags, target_industries=targets,
                        status="published", published_at=datetime.now(timezone.utc), routing_status="pending",
                        embedding=embed_one(f"{title}\n{content}\n{' '.join(tags)}"))
            db.add(post)
            db.commit()
            try:
                enqueue_route_post(post.id)
                print(f"published + queued routing: {title[:50]}")
            except RedisError as exc:
                post.routing_status = "failed"
                db.commit()
                print(f"published but Redis unavailable ({exc}); use POST /posts/{{id}}/reroute later")

    cred_path.write_text(json.dumps(creds, indent=2))
    cred_path.chmod(0o600)
    print(f"credentials written to {cred_path.resolve()}")


if __name__ == "__main__":
    main()
