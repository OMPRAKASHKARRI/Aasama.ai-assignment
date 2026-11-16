"""Demo webhook receiver that VERIFIES HMAC signatures:  python -m app.scripts.mock_receiver

Listens on 127.0.0.1:9101, path /hooks/<slug>. Secrets come from seed_credentials.json (written by the
seed script). It doubles as a reference implementation of correct receiver-side verification.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app.security import DELIVERY_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_signature

PORT = 9101
CREDS = json.loads(Path("seed_credentials.json").read_text()) if Path("seed_credentials.json").exists() else {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        slug = self.path.rstrip("/").split("/")[-1]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(min(length, 1_000_000))
        secret = CREDS.get(slug, {}).get("webhook_secret")
        ok = bool(secret) and verify_signature(
            secret, body, self.headers.get(SIGNATURE_HEADER, ""), self.headers.get(TIMESTAMP_HEADER, ""))
        if not ok:
            print(f"[{slug}] REJECTED invalid signature")
            self.send_response(401)
            self.end_headers()
            return
        data = json.loads(body)
        print(f"[{slug}] VERIFIED delivery {self.headers.get(DELIVERY_HEADER)}: "
              f"'{data['post']['title']}' score={data['relevance']['score']}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_: object) -> None:
        return


if __name__ == "__main__":
    print(f"mock receiver on http://127.0.0.1:{PORT}  ({len(CREDS)} agents known)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
