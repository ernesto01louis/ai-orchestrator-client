"""Authentication hooks.

Phase 1.6 of the orchestrator has no server-side auth — :class:`BearerTokenAuth`
ships now as a forward-compat shell so consumer code can already write::

    OrchestratorClient(auth=BearerTokenAuth(os.environ["TOKEN"]))

When Phase 1.7 lands token auth on the server, no client change is
needed: the same instance starts being honored.

The :class:`AuthProvider` protocol exposes ``get_headers()`` rather than
adapting :class:`httpx.Auth` directly because both the HTTP and (Phase F)
WebSocket transports need credentials, and ``httpx.Auth`` is a request-flow
generator unsuitable for the WS leg.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AuthProvider(Protocol):
    """Returns headers to attach to every outgoing request (HTTP and WS)."""

    def get_headers(self) -> dict[str, str]: ...


class BearerTokenAuth:
    """RFC 6750 ``Authorization: Bearer <token>`` header.

    No-op vs the Phase 1.6 orchestrator (server ignores Authorization).
    Phase 1.7 will start honoring it without breaking changes.
    """

    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("BearerTokenAuth requires a non-empty token")
        self._token = token

    def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}
