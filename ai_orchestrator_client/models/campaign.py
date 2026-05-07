"""Campaign request, record, ack, tree, and control-ack models.

Mirrors core/campaign.py (CampaignTemplate, CampaignCreate, Campaign,
CampaignRun) and the ad-hoc dict envelopes returned by api/routes.py
campaign endpoints (POST /campaigns, GET /campaigns/{id},
GET /campaigns/{id}/tree, POST /campaigns/{id}/{pause,resume,abort}).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from .status import CampaignStatus


class CampaignTemplate(BaseModel):
    """OrchestrateRequest skeleton applied to every child run.

    String fields may contain ``{param}`` placeholders that are filled
    from the per-combo params dict at expansion time on the server.
    """

    project_name: str
    prompt: str
    planner_model: str
    generator_models: list[str]
    judge_model: str
    deploy_target: str
    inspector_model: str | None = None
    optimizer_model: str | None = None
    troubleshooter_model: str | None = None
    max_iterations: int | None = None
    reference_files: list[str] | None = None


class CampaignCreate(BaseModel):
    """POST /campaigns body. Mirrors core.campaign.CampaignCreate.

    ``hypothesis`` is REQUIRED and load-bearing for the evidence bundle:
    it satisfies REFORMS §1 pre-registration. Empty/whitespace-only
    values are rejected (server-side validator mirrored here).
    """

    name: str
    description: str | None = None
    hypothesis: str
    template: CampaignTemplate
    params: dict[str, list[Any]]
    max_runs: int | None = None
    parallelism: int = 1

    @field_validator("hypothesis")
    @classmethod
    def _hypothesis_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError(
                "hypothesis required (REFORMS §1 pre-registration); "
                "give the question this campaign sets out to answer"
            )
        return v.strip()


class CampaignRun(BaseModel):
    """One row of `Campaign.runs` — status as seen by the campaign runner."""

    run_id: str
    params: dict[str, Any]
    status: str = "queued"
    score: float | None = None


class Campaign(CampaignCreate):
    """GET /campaigns/{id} response — full server record."""

    id: str
    status: CampaignStatus = "queued"
    runs: list[CampaignRun] = []
    created_at: str
    updated_at: str
    completed_at: str | None = None


class CampaignAck(BaseModel):
    """POST /campaigns response."""

    campaign_id: str
    flow_run_id: str | None = None
    run_count: int
    status: str
    poll: str


class CampaignTreeRun(BaseModel):
    """One run in GET /campaigns/{id}/tree — live phase merged from RUN_STATUS."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    params: dict[str, Any]
    phase: str | None = None
    score: float | None = None
    completed: bool = False


class CampaignTreeView(BaseModel):
    """GET /campaigns/{id}/tree response."""

    campaign: Campaign
    runs: list[CampaignTreeRun]


class CampaignControlAck(BaseModel):
    """POST /campaigns/{id}/{pause,resume,abort} response.

    All three endpoints share this shape; exactly one of `paused` or
    `aborted` is set per call (pause sets paused=True, resume sets
    paused=False, abort sets aborted=True).
    """

    model_config = ConfigDict(extra="ignore")

    campaign_id: str
    flow_run_id: str | None = None
    paused: bool | None = None
    aborted: bool | None = None
