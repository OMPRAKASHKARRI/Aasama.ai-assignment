from __future__ import annotations

from fastapi import HTTPException, status

from app.security import detect_injection


def screen_untrusted(**fields: str | None) -> None:
    """Reject submissions that match prompt-injection patterns (422 with the matching rule names)."""
    hits = {name: detect_injection(value) for name, value in fields.items() if value}
    hits = {name: rules for name, rules in hits.items() if rules}
    if hits:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "prompt_injection_detected", "message": "content looks like an attempt to "
                    "manipulate other AI agents and was rejected", "fields": hits},
        )
