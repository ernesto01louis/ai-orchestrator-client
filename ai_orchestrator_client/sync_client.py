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
    Campaign,
    CampaignAck,
    CampaignControlAck,
    CampaignCreate,
    CampaignTreeView,
    CampaignVerifyResult,
    CapabilityInvokeResult,
    ConsumerAck,
    ConsumerRecord,
    ConsumerRegistration,
    EvidencePush,
    MemoryWrite,
    Notification,
    OrchestrateAck,
    OrchestrateRequest,
    RunStatus,
    RunVerifyResult,
    VaultNote,
)


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

    # ----- campaign lifecycle -----------------------------------------

    def start_campaign(self, req: CampaignCreate) -> CampaignAck:
        """Submit a campaign (parameter sweep). Returns immediately with id."""
        resp = self._request(
            "POST", "/campaigns", json=req.model_dump(exclude_none=False)
        )
        return CampaignAck.model_validate(resp.json())

    def list_campaigns(self) -> list[dict[str, Any]]:
        """Server-side summary list (id, name, status, run_count, mean_score, ...)."""
        body: dict[str, Any] = self._request("GET", "/campaigns").json()
        items = body.get("campaigns", []) if isinstance(body, dict) else body
        result: list[dict[str, Any]] = list(items)
        return result

    def get_campaign(self, campaign_id: str) -> Campaign:
        """Full campaign record from /campaigns/{id}."""
        resp = self._request("GET", f"/campaigns/{campaign_id}")
        return Campaign.model_validate(resp.json())

    def get_campaign_tree(self, campaign_id: str) -> CampaignTreeView:
        """Tree view: campaign + per-run live phase merged from RUN_STATUS."""
        resp = self._request("GET", f"/campaigns/{campaign_id}/tree")
        return CampaignTreeView.model_validate(resp.json())

    def pause_campaign(self, campaign_id: str) -> CampaignControlAck:
        resp = self._request("POST", f"/campaigns/{campaign_id}/pause")
        return CampaignControlAck.model_validate(resp.json())

    def resume_campaign(self, campaign_id: str) -> CampaignControlAck:
        resp = self._request("POST", f"/campaigns/{campaign_id}/resume")
        return CampaignControlAck.model_validate(resp.json())

    def abort_campaign(self, campaign_id: str) -> CampaignControlAck:
        """Best-effort: stops new runs spawning; in-flight runs continue (Prefect)."""
        resp = self._request("POST", f"/campaigns/{campaign_id}/abort")
        return CampaignControlAck.model_validate(resp.json())

    def verify_campaign_merkle(self, campaign_id: str) -> CampaignVerifyResult:
        """Re-validate the campaign Merkle root (Phase 1.5 orchestrator surface)."""
        resp = self._request("GET", f"/campaigns/{campaign_id}/verify-merkle")
        return CampaignVerifyResult.model_validate(resp.json())

    # ----- evidence (Phase 1.2 orchestrator surface) -----------------

    def get_evidence(self, campaign_id: str) -> dict[str, Any]:
        """Full evidence-bundle JSON for a campaign."""
        result: dict[str, Any] = self._request(
            "GET", f"/campaigns/{campaign_id}/evidence"
        ).json()
        return result

    def download_evidence_crate(self, campaign_id: str) -> bytes:
        """Download the RO-Crate ZIP. Returns the raw bytes for caller to write."""
        resp = self._request("GET", f"/campaigns/{campaign_id}/evidence.crate.zip")
        return resp.content

    def refresh_evidence(self, campaign_id: str) -> dict[str, Any]:
        """Force-rebuild the evidence bundle (e.g. after a calculator plugin lands)."""
        result: dict[str, Any] = self._request(
            "POST", f"/campaigns/{campaign_id}/evidence/refresh"
        ).json()
        return result

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

    # ----- consumer registry (Phase 3.6) ------------------------------

    def register_consumer(self, reg: ConsumerRegistration) -> ConsumerAck:
        """Register (or upsert) an external consumer with the orchestrator."""
        resp = self._request(
            "POST", "/consumers/register", json=reg.model_dump(exclude_none=False)
        )
        return ConsumerAck.model_validate(resp.json())

    def list_consumers(self) -> list[ConsumerRecord]:
        """List registered consumers (the capability-discovery surface)."""
        body: dict[str, Any] = self._request("GET", "/consumers").json()
        items = body.get("consumers", []) if isinstance(body, dict) else body
        return [ConsumerRecord.model_validate(c) for c in items]

    def get_consumer(self, consumer_id: str) -> ConsumerRecord:
        """Fetch one registered consumer's record."""
        resp = self._request("GET", f"/consumers/{consumer_id}")
        return ConsumerRecord.model_validate(resp.json())

    def deregister_consumer(self, consumer_id: str) -> dict[str, Any]:
        """Remove a consumer from the registry."""
        result: dict[str, Any] = self._request(
            "DELETE", f"/consumers/{consumer_id}"
        ).json()
        return result

    def consumer_heartbeat(self, consumer_id: str) -> dict[str, Any]:
        """Send a liveness ping for a registered consumer."""
        result: dict[str, Any] = self._request(
            "POST", f"/consumers/{consumer_id}/heartbeat"
        ).json()
        return result

    def invoke_capability(
        self, capability: str, payload: dict[str, Any] | None = None
    ) -> CapabilityInvokeResult:
        """Dispatch a capability call to whichever consumer offers it."""
        resp = self._request(
            "POST",
            f"/capabilities/{capability}/invoke",
            json={"payload": payload or {}},
        )
        return CapabilityInvokeResult.model_validate(resp.json())

    # ----- consumer data-plane push (Phase 3.6) -----------------------

    def write_memory(self, consumer_id: str, content: str) -> dict[str, Any]:
        """Push a Hindsight memory entry on behalf of a consumer."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/consumers/{consumer_id}/memory",
            json=MemoryWrite(content=content).model_dump(),
        ).json()
        return result

    def write_vault_note(
        self, consumer_id: str, note: VaultNote
    ) -> dict[str, Any]:
        """Write an L5 vault note on behalf of a consumer."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/consumers/{consumer_id}/vault",
            json=note.model_dump(),
        ).json()
        return result

    def send_notification(
        self, consumer_id: str, notification: Notification
    ) -> dict[str, Any]:
        """Fire an ntfy/Gotify notification on behalf of a consumer."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/consumers/{consumer_id}/notify",
            json=notification.model_dump(exclude_none=False),
        ).json()
        return result

    def push_evidence(
        self, consumer_id: str, evidence: EvidencePush
    ) -> dict[str, Any]:
        """Persist a consumer-produced evidence bundle on the orchestrator."""
        result: dict[str, Any] = self._request(
            "POST",
            f"/consumers/{consumer_id}/evidence",
            json=evidence.model_dump(exclude_none=False),
        ).json()
        return result
