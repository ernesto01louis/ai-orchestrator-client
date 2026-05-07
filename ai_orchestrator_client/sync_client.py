"""Sync ``OrchestratorClient`` — wraps the orchestrator HTTP API with httpx.Client.

Surface mirrors the openai-python style: short verbs (``run``,
``health``, ``pause``), explicit args, typed return values backed by
the Pydantic mirrors in :mod:`ai_orchestrator_client.models`.

Phase C ships HTTP only. Async parity lands in Phase D; campaign + WS
streaming in Phase E + F.
"""
from __future__ import annotations

import threading
import time
from types import TracebackType
from typing import Any

import httpx

from ._auth import AuthProvider
from ._base import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
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

DEFAULT_POLL_INTERVAL_SECONDS = 0.5
DEFAULT_MAX_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_WAIT_TIMEOUT_SECONDS = 300.0


class OrchestratorClient:
    """Synchronous client for the AI Orchestrator HTTP API.

    Use as a context manager so the underlying httpx.Client is closed::

        with OrchestratorClient(base_url="http://localhost:8000") as c:
            ack = c.run(req)
            status = c.wait_for_completion(ack.run_id, timeout=600)
            result = c.get_result(ack.run_id)
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        auth: AuthProvider | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = normalize_base_url(base_url)
        self._auth = auth
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=default_headers(),
            transport=transport,
        )

    # ----- context manager + close ------------------------------------

    def __enter__(self) -> OrchestratorClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # ----- core HTTP helper -------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        # Merge fresh AuthProvider headers per request so a token-rotating
        # provider always sends current credentials. Per-request headers
        # take precedence over httpx.Client default headers.
        if self._auth is not None:
            headers = dict(kwargs.get("headers") or {})
            headers.update(self._auth.get_headers())
            kwargs["headers"] = headers
        resp = self._http.request(method, path, **kwargs)
        raise_for_status(resp)
        return resp

    # ----- health + control + meta ------------------------------------

    def health(self) -> dict[str, Any]:
        """Return the orchestrator's health snapshot (free dict).

        Server returns nested dicts for orchestrator, ollama_servers,
        hindsight, etc. Shape varies; consumers parse what they need.
        """
        result: dict[str, Any] = self._request("GET", "/health").json()
        return result

    def control_status(self) -> dict[str, Any]:
        """Return ``{paused: bool, active_runs: int}`` from /control/status."""
        result: dict[str, Any] = self._request("GET", "/control/status").json()
        return result

    def pause(self) -> dict[str, Any]:
        """Pause the orchestrator globally (rejects new runs).

        Idempotent: checks /control/status first and is a no-op when
        already paused. Server's /control/pause is a TOGGLE — guarding
        the call protects callers from accidentally un-pausing.
        """
        current = self.control_status()
        if current.get("paused") is True:
            return current
        result: dict[str, Any] = self._request("POST", "/control/pause").json()
        return result

    def resume(self) -> dict[str, Any]:
        """Resume the orchestrator if currently paused.

        Idempotent: checks /control/status first and is a no-op when
        already running. Avoids the toggle-endpoint footgun where a
        naive ``resume()`` against a running orchestrator would pause
        it.
        """
        current = self.control_status()
        if current.get("paused") is False:
            return current
        result: dict[str, Any] = self._request("POST", "/control/pause").json()
        return result

    def restart(self) -> dict[str, Any]:
        """Trigger a background restart of the orchestrator service."""
        result: dict[str, Any] = self._request("POST", "/control/restart").json()
        return result

    # ----- run lifecycle ----------------------------------------------

    def run(self, req: OrchestrateRequest) -> OrchestrateAck:
        """Submit an orchestration run. Returns immediately with run_id."""
        resp = self._request(
            "POST", "/orchestrate", json=req.model_dump(exclude_none=False)
        )
        return OrchestrateAck.model_validate(resp.json())

    def get_status(self, run_id: str) -> RunStatus:
        """Fetch one snapshot of /status/{run_id}."""
        resp = self._request("GET", f"/status/{run_id}")
        return RunStatus.model_validate(resp.json())

    def get_result(self, run_id: str) -> dict[str, Any]:
        """Fetch /result/{run_id} (server returns generator output verbatim).

        Returns the bare server JSON. For a stable typed wrapper, prefer
        :meth:`wait_for_completion` followed by reading
        :attr:`RunStatus.result`. Phase E will add a typed
        ``complete_run()`` helper that returns
        :class:`OrchestrateResult`.
        """
        result: dict[str, Any] = self._request("GET", f"/result/{run_id}").json()
        return result

    def verify_run(self, run_id: str) -> RunVerifyResult:
        """Force a manifest integrity check (Phase 1.5 orchestrator surface)."""
        resp = self._request("GET", f"/runs/{run_id}/verify")
        return RunVerifyResult.model_validate(resp.json())

    def tail_log(self, run_id: str) -> str:
        """Return the tail of the orchestrator's run log as plain text."""
        resp = self._request("GET", f"/logs/{run_id}/tail")
        return resp.text

    # ----- wait_for_completion ----------------------------------------

    def wait_for_completion(
        self,
        run_id: str,
        *,
        timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_poll_interval: float = DEFAULT_MAX_POLL_INTERVAL_SECONDS,
        stop_event: threading.Event | None = None,
    ) -> RunStatus:
        """Poll /status/{run_id} until completed=True (or timeout/interrupt).

        Trusts only the boolean ``completed`` field as terminal —
        ``phase`` strings can repeat under Prefect task retries (a
        transient failure flips executing → executing).

        Backoff: starts at ``poll_interval``, multiplies by 1.5 each
        attempt, capped at ``max_poll_interval``. The 1.5× multiplier
        favors short-run UX (~7 polls in the first 14s) over server
        load; bump ``poll_interval`` upward for very-long-running runs.

        When ``stop_event`` is provided the sleep between polls uses
        ``Event.wait`` so the caller (or signal handler) can interrupt
        cleanly; raises :class:`WaitInterrupted`. When omitted the
        sleep is a plain ``time.sleep``.

        Raises:
            RunFailed: completed=True with a non-empty error field.
            WaitTimeout: ``timeout`` seconds elapsed without completion.
            WaitInterrupted: ``stop_event`` was set during a sleep.
        """
        start = time.monotonic()
        deadline = start + timeout
        interval = poll_interval

        while True:
            status = self.get_status(run_id)
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
                time.sleep(wait_for)
            elif stop_event.wait(wait_for):
                raise WaitInterrupted(run_id, status.phase)
            interval = min(interval * 1.5, max_poll_interval)
