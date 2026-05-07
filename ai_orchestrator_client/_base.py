"""Transport-agnostic helpers shared by the sync and async clients.

These are stand-alone functions, not a base class — the sync vs async
clients each own their httpx Client/AsyncClient instance, and the only
shared logic is URL building, error mapping, and default-header
construction.

Auth headers are NOT baked into the default-headers dict — they're
merged per-request by the client so a token-rotating
:class:`AuthProvider` always sends the freshest credentials.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

from ._errors import NotFound, OrchestratorAPIError, ServiceUnavailable, ValidationError

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 30.0


def _user_agent() -> str:
    try:
        return f"ai-orchestrator-client/{version('ai-orchestrator-client')}"
    except PackageNotFoundError:  # pragma: no cover — only triggers in unusual envs
        return "ai-orchestrator-client"


USER_AGENT = _user_agent()


def normalize_base_url(base_url: str) -> str:
    """Strip trailing slashes so ``urljoin``-style concat is unambiguous."""
    return base_url.rstrip("/") or base_url


def default_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Default-headers dict for ``httpx.Client(headers=...)``.

    Auth is intentionally NOT included — the sync/async clients merge
    fresh ``AuthProvider.get_headers()`` per request so a JWT-rotating
    provider always sends current credentials.
    """
    headers: dict[str, str] = {"User-Agent": USER_AGENT}
    if extra:
        headers.update(extra)
    return headers


def raise_for_status(resp: httpx.Response) -> None:
    """Map a non-2xx response to a typed SDK exception.

    Reads ``detail`` from the FastAPI error body when present (FastAPI's
    standard error envelope is ``{"detail": "<message>"}`` for plain
    errors and ``{"detail": [{loc, msg, type}, ...]}`` for 422
    validation errors).
    """
    if resp.is_success:
        return
    body: Any = None
    message = resp.text
    try:
        body = resp.json()
        if isinstance(body, dict) and "detail" in body:
            detail = body["detail"]
            message = str(detail) if not isinstance(detail, list) else _summarize_422(detail)
    except (ValueError, httpx.DecodingError):
        body = resp.text or None

    if resp.status_code == 404:
        raise NotFound(message, body=body)
    if resp.status_code == 422:
        raise ValidationError(message, body=body)
    if resp.status_code == 503:
        raise ServiceUnavailable(message, body=body)
    raise OrchestratorAPIError(resp.status_code, message, body=body)


def _summarize_422(detail: list[Any]) -> str:
    """Render FastAPI's structured 422 detail list as a one-line message."""
    parts: list[str] = []
    for entry in detail:
        if not isinstance(entry, dict):
            continue
        loc = ".".join(str(p) for p in entry.get("loc", []) if p != "body")
        msg = entry.get("msg", "")
        parts.append(f"{loc}: {msg}" if loc else str(msg))
    return "; ".join(parts) or "validation error"
