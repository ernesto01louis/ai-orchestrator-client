"""Orchestrate (single-run) request, ack, status, and result models.

Mirrors orchestration/__init__.py:572 (OrchestrateRequest) and the ad-hoc
dict envelopes returned by api/routes.py:170 (POST /orchestrate),
api/routes.py:200 (GET /status/{run_id}), and api/routes.py:250
(GET /result/{run_id}).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from .status import ManifestStatus


class OrchestrateRequest(BaseModel):
    """POST /orchestrate body. Mirrors orchestration.OrchestrateRequest.

    Strings may NOT contain {param} placeholders here — placeholders are
    only honored by the campaign expander on CampaignTemplate (see
    campaign.CampaignTemplate). Use start_campaign() for parameter sweeps.
    """

    project_name: str
    prompt: str

    planner_model: str
    # Server schema is bare `list` (untyped items). The SDK narrows to
    # list[str] because every shipped agent role consumes a string model
    # name; widen this if a future server release accepts per-model dicts.
    generator_models: list[str]
    judge_model: str

    inspector_model: str | None = None
    optimizer_model: str | None = None
    troubleshooter_model: str | None = None

    max_iterations: int | None = None
    deploy_target: str
    reference_files: list[str] | None = None


class OrchestrateAck(BaseModel):
    """POST /orchestrate response. Server returns immediately with this."""

    run_id: str
    flow_run_id: str | None = None
    status: str
    poll: str


class RunStatus(BaseModel):
    """GET /status/{run_id} response — superset of fields seen across phases.

    Trust only `completed` for terminal detection; `phase` is advisory and
    can repeat on Prefect task retries. The server populates `error` and
    `result` only when `completed=True`; both are None during execution.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str
    phase: str
    score: float | None = None
    completed: bool

    flow_run_id: str | None = None
    project: str | None = None
    target: str | None = None

    error: str | None = None
    result: dict[str, Any] | None = None
    manifest_status: ManifestStatus | None = None


class RunningResult(BaseModel):
    """GET /result/{run_id} response when the run is still running."""

    run_id: str
    status: str
    phase: str
    score: float | None = None


class OrchestrateResult(BaseModel):
    """Stable wrapper around a completed run's result.

    Not 1:1 with GET /result/{run_id} — the server returns the bare
    generator dict at top level when complete. The SDK assembles this
    wrapper from /status/{run_id} + /result/{run_id} so callers always
    get the stable fields regardless of what the generator emitted.

    The inner `payload` is generator-dependent and intentionally untyped —
    each generator agent returns whatever shape it produced (typically a
    dict with score, code, judge_verdict, ...).
    """

    run_id: str
    completed: bool
    phase: str
    score: float | None = None
    error: str | None = None
    manifest_status: ManifestStatus | None = None
    payload: dict[str, Any] | None = None
