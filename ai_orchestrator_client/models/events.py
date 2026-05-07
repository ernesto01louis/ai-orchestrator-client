"""Live-stream event models for /ws broadcasts (Phase F).

Server's /ws endpoint emits two message shapes (see core/runtime.py:120
and core/runtime.py:184):

    {"type": "log",    "run_id": "...", "line": "...", "phase": "..."}
    {"type": "status", "run_id": "...", "phase": "...", "score": N,
                       "completed": bool, "error": str|None,
                       "project": str, "target": str}

Plus heartbeat ``{"type": "pong"}`` in response to client pings, which
the SDK consumes internally rather than yielding.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LogEvent(BaseModel):
    """One ``{"type": "log", ...}`` broadcast from /ws."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    line: str
    phase: str | None = None


class StatusEvent(BaseModel):
    """One ``{"type": "status", ...}`` broadcast from /ws."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    phase: str
    score: float | None = None
    completed: bool = False
    error: str | None = None
    project: str | None = None
    target: str | None = None
