"""Async ``AsyncOrchestratorClient`` — async mirror of :class:`OrchestratorClient`.

Identical method signatures and semantics; the only differences are
``async def`` + ``asyncio.sleep`` / ``asyncio.Event`` instead of the
threading equivalents. Phase E adds campaign endpoints + streaming;
Phase F adds WebSocket log streaming on this class only.

NOTE: sync_client.py and async_client.py are intentionally kept as
parallel transport-specific files rather than sharing a base class.
Phase F will diverge them further (WS streaming is async-only) and
collapsing them would force ``if asyncio: ... else: ...`` branches in
the wait/sleep helpers.
"""
from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any

import httpx

from ._auth import AuthProvider
from ._base import (
    DEFAULT_BASE_URL,
    DEFAULT_MAX_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    default_headers,
    normalize_base_url,
    raise_for_status,
)
from ._errors import RunFailed, WaitInterrupted, WaitTimeout
from .models import (
    OrchestrateAck,
    OrchestrateRequest,
    RunStatus,
    RunVerifyResult,
)


class AsyncOrchestratorClient:
    """Asynchronous client for the AI Orchestrator HTTP API.

    Use as an ``async`` context manager so the underlying
    :class:`httpx.AsyncClient` is closed::

        async with AsyncOrchestratorClient(base_url="http://localhost:8000") as c:
            ack = await c.run(req)
            status = await c.wait_for_completion(ack.run_id, timeout=600)
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        auth: AuthProvider | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = normalize_base_url(base_url)
        self._auth = auth
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=default_headers(),
            transport=transport,
        )

    # ----- async context manager + close ------------------------------

    async def __aenter__(self) -> AsyncOrchestratorClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----- core HTTP helper -------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._auth is not None:
            headers = dict(kwargs.get("headers") or {})
            headers.update(self._auth.get_headers())
            kwargs["headers"] = headers
        resp = await self._http.request(method, path, **kwargs)
        raise_for_status(resp)
        return resp

    # ----- health + control + meta ------------------------------------

    async def health(self) -> dict[str, Any]:
        resp = await self._request("GET", "/health")
        result: dict[str, Any] = resp.json()
        return result

    async def control_status(self) -> dict[str, Any]:
        resp = await self._request("GET", "/control/status")
        result: dict[str, Any] = resp.json()
        return result

    async def pause(self) -> dict[str, Any]:
        """Idempotent pause — no-op when already paused (toggle-endpoint guard)."""
        current = await self.control_status()
        if current.get("paused") is True:
            return current
        resp = await self._request("POST", "/control/pause")
        result: dict[str, Any] = resp.json()
        return result

    async def resume(self) -> dict[str, Any]:
        """Idempotent resume — no-op when already running (toggle-endpoint guard)."""
        current = await self.control_status()
        if current.get("paused") is False:
            return current
        resp = await self._request("POST", "/control/pause")
        result: dict[str, Any] = resp.json()
        return result

    async def restart(self) -> dict[str, Any]:
        resp = await self._request("POST", "/control/restart")
        result: dict[str, Any] = resp.json()
        return result

    # ----- run lifecycle ----------------------------------------------

    async def run(self, req: OrchestrateRequest) -> OrchestrateAck:
        """Submit an orchestration run. Returns immediately with run_id."""
        resp = await self._request(
            "POST", "/orchestrate", json=req.model_dump(exclude_none=False)
        )
        return OrchestrateAck.model_validate(resp.json())

    async def get_status(self, run_id: str) -> RunStatus:
        """Fetch one snapshot of /status/{run_id}."""
        resp = await self._request("GET", f"/status/{run_id}")
        return RunStatus.model_validate(resp.json())

    async def get_result(self, run_id: str) -> dict[str, Any]:
        """Fetch /result/{run_id} verbatim. Phase E will add a typed wrapper."""
        resp = await self._request("GET", f"/result/{run_id}")
        result: dict[str, Any] = resp.json()
        return result

    async def verify_run(self, run_id: str) -> RunVerifyResult:
        """Force a manifest integrity check (Phase 1.5 surface)."""
        resp = await self._request("GET", f"/runs/{run_id}/verify")
        return RunVerifyResult.model_validate(resp.json())

    async def tail_log(self, run_id: str) -> str:
        """Return the tail of the orchestrator's run log as plain text."""
        resp = await self._request("GET", f"/logs/{run_id}/tail")
        return resp.text

    # ----- wait_for_completion ----------------------------------------

    async def wait_for_completion(
        self,
        run_id: str,
        *,
        timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_poll_interval: float = DEFAULT_MAX_POLL_INTERVAL_SECONDS,
        stop_event: asyncio.Event | None = None,
    ) -> RunStatus:
        """Async mirror of :meth:`OrchestratorClient.wait_for_completion`.

        Same semantics: ``completed=True`` is the only terminal signal,
        1.5× backoff to ``max_poll_interval``, ``stop_event`` raises
        :class:`WaitInterrupted`. Uses ``asyncio.sleep`` (no stop_event)
        or ``asyncio.wait_for(stop_event.wait(), ...)`` so a
        cancellation propagates as :class:`asyncio.CancelledError`.
        """
        start = time.monotonic()
        deadline = start + timeout
        interval = poll_interval

        while True:
            status = await self.get_status(run_id)
            if status.completed:
                if status.error:
                    raise RunFailed(run_id, status.error)
                return status

            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                raise WaitTimeout(run_id, status.phase, elapsed=now - start)

            wait_for = min(interval, remaining)
            if stop_event is None:
                await asyncio.sleep(wait_for)
            else:
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait_for)
                # Narrow except: asyncio.CancelledError (BaseException) must
                # propagate so an awaiting caller can cancel the wait cleanly.
                # asyncio.TimeoutError is an alias for builtin TimeoutError
                # since Python 3.11 — one name suffices.
                except TimeoutError:
                    pass
                else:
                    raise WaitInterrupted(run_id, status.phase)
            interval = min(interval * 1.5, max_poll_interval)
