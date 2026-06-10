"""Redact secrets from strings before they reach logs or HTTP responses."""

from __future__ import annotations

import re

_CONN = re.compile(r"(?:postgres(?:ql)?|bolt(?:\+s)?)://\S+", re.IGNORECASE)
_BEARER = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_TOKEN = re.compile(r"tok_[A-Za-z0-9_-]+")
_KV_SECRET = re.compile(
    r"(?i)(password|passwd|pwd|secret|api[_-]?key|agent[_-]?token|neo4j[_-]?password)"
    r"\s*[=:]\s*\S+",
)


def sanitize_error(message: str | None) -> str:
    """Strip connection strings and credential-like fragments from error text."""
    if not message:
        return ""
    out = str(message)
    out = _CONN.sub("postgresql://[redacted]", out)
    out = _BEARER.sub("Bearer [redacted]", out)
    out = _TOKEN.sub("tok_[redacted]", out)
    out = _KV_SECRET.sub(r"\1=[redacted]", out)
    return out