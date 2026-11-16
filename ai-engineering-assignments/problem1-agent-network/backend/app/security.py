"""Security primitives: text sanitisation, prompt-injection screening, SSRF guard, HMAC signing.

Design notes
------------
* Everything an agent submits (manifesto, posts, comments) is *untrusted* and will eventually be read by
  other LLM-driven agents. We (1) normalise it, (2) reject content matching known injection patterns,
  and (3) always deliver it inside a clearly-labelled ``untrusted`` envelope. Pattern matching is a
  defence-in-depth layer, NOT a guarantee; receivers must still treat content as data.
* Webhook URLs are validated against SSRF both at registration and again right before every delivery.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import socket
import time
import unicodedata
from urllib.parse import urlsplit

# ---------------------------------------------------------------- text sanitisation

# zero-width, bidi-override/isolate and other invisible formatting characters used to hide payloads
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_BLANK = re.compile(r"\n{3,}")


def sanitize_text(text: str) -> str:
    """Normalise to NFKC, drop invisible/control characters, collapse blank-line floods, trim."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()


_INJECTION_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("override_instructions", re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b"
        r"[^.\n]{0,30}\b(instruction|instructions|prompt|prompts|rules|guidelines|directives|context)\b", re.I)),
    ("role_hijack", re.compile(
        r"\b(you are now|from now on you are|act as (?:if you are )?(?:an?|the)\b|pretend (?:to be|you are)|"
        r"new persona|developer mode|dan mode|jailbreak)\b", re.I)),
    ("prompt_exfiltration", re.compile(
        r"\b(reveal|show|print|repeat|leak|output|disclose|tell me)\b[^.\n]{0,40}"
        r"\b(system prompt|hidden prompt|your instructions|your prompt|api[ _-]?key|secret|credentials?|"
        r"password|webhook secret|token)\b", re.I)),
    ("credential_request", re.compile(
        r"\b(send|forward|post|email|submit|exfiltrate)\b[^.\n]{0,40}"
        r"\b(api[ _-]?keys?|secrets?|credentials?|passwords?|tokens?)\b", re.I)),
    ("chat_template_tokens", re.compile(
        r"(<\|im_(?:start|end)\|>|<\|system\|>|<\|assistant\|>|\[/?INST\]|<<SYS>>|<\|begin_of_text\|>|"
        r"^\s*(?:system|assistant)\s*:\s)", re.I | re.M)),
    ("fake_system_block", re.compile(r"(#{2,}\s*(?:system|instruction)s?\b|begin (?:system|admin) (?:prompt|message))", re.I)),
    ("tool_invocation", re.compile(r"\b(call|invoke|execute|run)\b[^.\n]{0,25}\b(function|tool|command|shell|curl|bash)\b", re.I)),
    ("active_content", re.compile(r"(<\s*script\b|javascript:|<\s*iframe\b|onerror\s*=)", re.I)),
]


def detect_injection(text: str) -> list[str]:
    """Return the names of every injection rule that matches ``text`` (empty list = clean)."""
    probe = sanitize_text(text)
    return [name for name, rx in _INJECTION_RULES if rx.search(probe)]


# ---------------------------------------------------------------- API keys / secrets

API_KEY_PREFIX = "ank_"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """SHA-256 is appropriate here: keys are 256-bit random values, so no slow KDF/salt is needed."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_webhook_secret() -> str:
    return "whsec_" + secrets.token_hex(32)


# ---------------------------------------------------------------- HMAC-SHA256 webhook signing

SIGNATURE_HEADER = "X-AgentNet-Signature"
TIMESTAMP_HEADER = "X-AgentNet-Timestamp"
DELIVERY_HEADER = "X-AgentNet-Delivery"
DEFAULT_TOLERANCE_SECONDS = 300


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 over ``"<timestamp>." + body``; binding the timestamp prevents replay of old bodies."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return mac.hexdigest()


def sign_payload(secret: str, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    return {TIMESTAMP_HEADER: ts, SIGNATURE_HEADER: "sha256=" + compute_signature(secret, ts, body)}


def verify_signature(
    secret: str, body: bytes, signature_header: str, timestamp_header: str,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS, now: float | None = None,
) -> bool:
    """Reference verifier for webhook receivers: constant-time compare + replay window."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    try:
        ts = int(timestamp_header)
    except (TypeError, ValueError):
        return False
    if abs((time.time() if now is None else now) - ts) > tolerance_seconds:
        return False
    expected = compute_signature(secret, timestamp_header, body)
    return hmac.compare_digest(expected, signature_header[len("sha256="):])


# ---------------------------------------------------------------- SSRF guard

class UnsafeWebhookURL(ValueError):
    """Raised when a webhook URL is malformed or targets a disallowed network location."""


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_public(ip.ipv4_mapped)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


def validate_webhook_url(url: str, allow_private: bool = False, resolve: bool = True) -> str:
    """Validate ``url`` and return it normalised. Raises :class:`UnsafeWebhookURL`.

    Rules: https only (http allowed in dev), no embedded credentials, sane port, host must resolve and
    *every* resolved address must be public (blocks 127/8, 10/8, 169.254/16 cloud metadata, ::1, ...).
    """
    url = url.strip()
    if len(url) > 2048:
        raise UnsafeWebhookURL("URL too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeWebhookURL(f"malformed URL: {exc}") from exc
    if parts.scheme not in ("https", "http"):
        raise UnsafeWebhookURL("scheme must be https")
    if parts.scheme == "http" and not allow_private:
        raise UnsafeWebhookURL("scheme must be https")
    if parts.username or parts.password:
        raise UnsafeWebhookURL("credentials in URL are not allowed")
    host = parts.hostname
    if not host:
        raise UnsafeWebhookURL("missing host")
    if allow_private:
        return url
    if port is not None and port not in (443, 8443):
        raise UnsafeWebhookURL("port not allowed (use 443 or 8443)")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [literal]
    elif not resolve:
        return url
    else:
        try:
            infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise UnsafeWebhookURL(f"host does not resolve: {host}") from exc
        addresses = [ipaddress.ip_address(i[4][0]) for i in infos]
    for addr in addresses:
        if not _is_public(addr):
            raise UnsafeWebhookURL("URL resolves to a non-public address")
    return url
