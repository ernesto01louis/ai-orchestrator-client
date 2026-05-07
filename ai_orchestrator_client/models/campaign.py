"""Campaign request, record, ack, tree, and control-ack models.

Mirrors core/campaign.py (CampaignTemplate, CampaignCreate, Campaign,
CampaignRun) and the ad-hoc dict envelopes returned by api/routes.py
campaign endpoints (POST /campaigns, GET /campaigns/{id},
GET /campaigns/{id}/tree, POST /campaigns/{id}/{pause,resume,abort}).
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any, overload

from pydantic import BaseModel, ConfigDict, field_validator

from .status import CampaignStatus

if TYPE_CHECKING:
    from .._base import (
        DEFAULT_MAX_POLL_INTERVAL_SECONDS as _DEFAULT_MAX_POLL,
    )
    from .._base import (
        DEFAULT_POLL_INTERVAL_SECONDS as _DEFAULT_POLL,
    )
    from ..async_client import AsyncOrchestratorClient
    from ..sync_client import OrchestratorClient
else:
    from .._base import (
        DEFAULT_MAX_POLL_INTERVAL_SECONDS as _DEFAULT_MAX_POLL,
    )
    from .._base import (
        DEFAULT_POLL_INTERVAL_SECONDS as _DEFAULT_POLL,
    )


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

    @overload
    def iter_runs(
        self,
        client: OrchestratorClient,
        *,
        poll_interval_seconds: float = ...,
        max_poll_interval_seconds: float = ...,
    ) -> Iterator[CampaignTreeRun]: ...

    @overload
    def iter_runs(
        self,
        client: AsyncOrchestratorClient,
        *,
        poll_interval_seconds: float = ...,
        max_poll_interval_seconds: float = ...,
    ) -> AsyncIterator[CampaignTreeRun]: ...

    def iter_runs(
        self,
        client: OrchestratorClient | AsyncOrchestratorClient,
        *,
        poll_interval_seconds: float = _DEFAULT_POLL,
        max_poll_interval_seconds: float = _DEFAULT_MAX_POLL,
    ) -> Iterator[CampaignTreeRun] | AsyncIterator[CampaignTreeRun]:
        """Stream :class:`CampaignTreeRun` rows as they appear server-side.

        Solves the empty-``runs[]`` race after ``start_campaign`` (server
        writes the campaign record before its runner thread has populated
        any combos): polls /campaigns/{id}/tree, yielding each run id the
        first time it appears, and only terminates when the campaign
        reached a terminal status AND the most recent poll yielded zero
        new run ids.

        Dispatches on ``client`` type — passes a sync client returns a
        generator, an async client returns an async generator. Use::

            for run in campaign.iter_runs(sync_client):
                ...

            async for run in campaign.iter_runs(async_client):
                ...
        """
        # Lazy imports to dodge the circular dependency with the client modules.
        from ..async_client import AsyncOrchestratorClient as _AC
        from ..streaming import _iter_runs_async, _iter_runs_sync

        if isinstance(client, _AC):
            return _iter_runs_async(
                client,
                self.id,
                poll_interval_seconds=poll_interval_seconds,
                max_poll_interval_seconds=max_poll_interval_seconds,
            )
        return _iter_runs_sync(
            client,
            self.id,
            poll_interval_seconds=poll_interval_seconds,
            max_poll_interval_seconds=max_poll_interval_seconds,
        )


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
