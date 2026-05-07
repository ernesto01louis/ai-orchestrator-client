"""Exception hierarchy for the SDK.

All exceptions inherit from :class:`OrchestratorError` so callers can
catch the whole family with one ``except`` clause. Specific subclasses
let callers handle expected failure modes (run failed, server paused,
unknown id) without parsing strings.
"""
from __future__ import annotations

from typing import Any


class OrchestratorError(Exception):
    """Base for every exception the SDK raises."""


class OrchestratorAPIError(OrchestratorError):
    """The server returned an unexpected HTTP error."""

    def __init__(self, status_code: int, message: str, body: Any = None) -> None:
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code
        self.body = body


class NotFound(OrchestratorAPIError):
    """The server returned 404 for the requested run/campaign id."""

    def __init__(self, message: str, body: Any = None) -> None:
        super().__init__(404, message, body)


class ServiceUnavailable(OrchestratorAPIError):
    """The server returned 503 (typically: orchestrator is paused).

    See ``OrchestratorClient.pause()`` / ``resume()``.
    """

    def __init__(self, message: str, body: Any = None) -> None:
        super().__init__(503, message, body)


class ValidationError(OrchestratorAPIError):
    """The server returned 422 (FastAPI request-body validation failure).

    ``detail`` on FastAPI's 422 envelope is a list of
    ``{"loc": [...], "msg": "...", "type": "..."}`` dicts; preserved
    verbatim on :attr:`body` for callers that want to render them.
    """

    def __init__(self, message: str, body: Any = None) -> None:
        super().__init__(422, message, body)

    @property
    def errors(self) -> list[dict[str, Any]]:
        """The raw FastAPI ``detail`` list, or [] when not list-shaped."""
        if isinstance(self.body, dict):
            detail = self.body.get("detail")
            if isinstance(detail, list):
                return [d for d in detail if isinstance(d, dict)]
        return []


class RunFailed(OrchestratorError):
    """A run reached completed=True with a non-empty ``error`` field.

    Raised by :meth:`OrchestratorClient.wait_for_completion` so callers
    don't have to inspect ``RunStatus.error`` themselves.
    """

    def __init__(self, run_id: str, error: str) -> None:
        super().__init__(f"run {run_id} failed: {error}")
        self.run_id = run_id
        self.error = error


class WaitTimeout(OrchestratorError):
    """``wait_for_completion`` exceeded its ``timeout`` budget."""

    def __init__(self, run_id: str, last_phase: str, elapsed: float) -> None:
        super().__init__(
            f"run {run_id} did not complete within {elapsed:.1f}s "
            f"(last phase: {last_phase})"
        )
        self.run_id = run_id
        self.last_phase = last_phase
        self.elapsed = elapsed


class WaitInterrupted(OrchestratorError):
    """``wait_for_completion`` was interrupted via its ``stop_event``."""

    def __init__(self, run_id: str, last_phase: str) -> None:
        super().__init__(
            f"wait for run {run_id} interrupted (last phase: {last_phase})"
        )
        self.run_id = run_id
        self.last_phase = last_phase
