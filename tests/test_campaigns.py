"""Phase E coverage: campaign CRUD/control/evidence + Campaign.iter_runs.

Mocked end-to-end via respx for both sync and async clients. Streaming
scenarios cover the empty-``runs[]`` race that motivates the polling
helper, mid-stream abort, and sync/async parity.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx

from ai_orchestrator_client import (
    AsyncOrchestratorClient,
    Campaign,
    CampaignCreate,
    CampaignTemplate,
    OrchestratorClient,
)

BASE = "http://orchestrator.test"


@pytest.fixture
def sync_client() -> Iterator[OrchestratorClient]:
    with OrchestratorClient(base_url=BASE) as c:
        yield c


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncOrchestratorClient]:
    async with AsyncOrchestratorClient(base_url=BASE) as c:
        yield c


def _campaign_template() -> CampaignTemplate:
    return CampaignTemplate(
        project_name="demo-{seed}",
        prompt="hi {language}",
        planner_model="m",
        generator_models=["m"],
        judge_model="m",
        deploy_target="local",
    )


def _campaign_create() -> CampaignCreate:
    return CampaignCreate(
        name="sweep",
        hypothesis="hello-world is invariant across seeds",
        template=_campaign_template(),
        params={"seed": [1, 2], "language": ["python", "bash"]},
    )


def _campaign_record(*, status: str = "queued", runs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = _campaign_create().model_dump()
    return {
        **payload,
        "id": "c-1",
        "status": status,
        "runs": runs or [],
        "created_at": "2026-05-07T00:00:00",
        "updated_at": "2026-05-07T00:01:00",
        "completed_at": "2026-05-07T00:05:00" if status == "completed" else None,
    }


def _tree_payload(*, status: str, run_ids: list[str], all_completed: bool = False) -> dict[str, Any]:
    return {
        "campaign": _campaign_record(
            status=status,
            runs=[{"run_id": rid, "params": {}, "status": "completed" if all_completed else "running"} for rid in run_ids],
        ),
        "runs": [
            {
                "run_id": rid,
                "params": {},
                "phase": "completed" if all_completed else "executing",
                "score": 0.5 if all_completed else None,
                "completed": all_completed,
            }
            for rid in run_ids
        ],
    }


# ---------- sync: campaign CRUD + control ----------------------------


@respx.mock
def test_sync_start_campaign(sync_client: OrchestratorClient) -> None:
    respx.post(f"{BASE}/campaigns").mock(
        return_value=httpx.Response(
            200,
            json={
                "campaign_id": "c-1",
                "flow_run_id": "f-1",
                "run_count": 4,
                "status": "started",
                "poll": "/campaigns/c-1",
            },
        )
    )
    ack = sync_client.start_campaign(_campaign_create())
    assert ack.campaign_id == "c-1"
    assert ack.run_count == 4


@respx.mock
def test_sync_list_campaigns(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns").mock(
        return_value=httpx.Response(
            200,
            json={"campaigns": [{"id": "c-1", "name": "sweep", "status": "completed"}]},
        )
    )
    items = sync_client.list_campaigns()
    assert items[0]["id"] == "c-1"


@respx.mock
def test_sync_get_campaign(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1").mock(
        return_value=httpx.Response(200, json=_campaign_record(status="running"))
    )
    c = sync_client.get_campaign("c-1")
    assert isinstance(c, Campaign)
    assert c.status == "running"


@respx.mock
def test_sync_get_campaign_tree(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        return_value=httpx.Response(
            200, json=_tree_payload(status="running", run_ids=["r-1"])
        )
    )
    tv = sync_client.get_campaign_tree("c-1")
    assert tv.runs[0].run_id == "r-1"


@respx.mock
def test_sync_pause_resume_abort(sync_client: OrchestratorClient) -> None:
    respx.post(f"{BASE}/campaigns/c-1/pause").mock(
        return_value=httpx.Response(
            200, json={"campaign_id": "c-1", "paused": True, "flow_run_id": "f-1"}
        )
    )
    respx.post(f"{BASE}/campaigns/c-1/resume").mock(
        return_value=httpx.Response(
            200, json={"campaign_id": "c-1", "paused": False, "flow_run_id": "f-1"}
        )
    )
    respx.post(f"{BASE}/campaigns/c-1/abort").mock(
        return_value=httpx.Response(
            200, json={"campaign_id": "c-1", "aborted": True, "flow_run_id": "f-1"}
        )
    )
    p = sync_client.pause_campaign("c-1")
    assert p.paused is True
    r = sync_client.resume_campaign("c-1")
    assert r.paused is False
    a = sync_client.abort_campaign("c-1")
    assert a.aborted is True


@respx.mock
def test_sync_verify_campaign_merkle_ok(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/verify-merkle").mock(
        return_value=httpx.Response(
            200,
            json={"campaign_id": "c-1", "valid": True, "status": "ok", "mismatches": []},
        )
    )
    v = sync_client.verify_campaign_merkle("c-1")
    assert v.valid is True
    assert v.status == "ok"


@respx.mock
def test_sync_verify_campaign_merkle_corrupted(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/verify-merkle").mock(
        return_value=httpx.Response(
            200,
            json={
                "campaign_id": "c-1",
                "valid": False,
                "status": "corrupted",
                "mismatches": ["root mismatch"],
            },
        )
    )
    v = sync_client.verify_campaign_merkle("c-1")
    assert v.valid is False
    assert "root mismatch" in v.mismatches[0]


# ---------- sync: evidence ------------------------------------------


@respx.mock
def test_sync_get_evidence(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/evidence").mock(
        return_value=httpx.Response(200, json={"bundle_id": "b-1", "artifacts": []})
    )
    bundle = sync_client.get_evidence("c-1")
    assert bundle["bundle_id"] == "b-1"


@respx.mock
def test_sync_download_evidence_crate(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/evidence.crate.zip").mock(
        return_value=httpx.Response(
            200,
            content=b"PK\x03\x04fake-zip-bytes",
            headers={"content-type": "application/zip"},
        )
    )
    blob = sync_client.download_evidence_crate("c-1")
    assert blob.startswith(b"PK\x03\x04")


@respx.mock
def test_sync_refresh_evidence(sync_client: OrchestratorClient) -> None:
    respx.post(f"{BASE}/campaigns/c-1/evidence/refresh").mock(
        return_value=httpx.Response(
            200,
            json={
                "campaign_id": "c-1",
                "bundle_id": "b-2",
                "artifact_count": 3,
                "calculator_count": 5,
            },
        )
    )
    out = sync_client.refresh_evidence("c-1")
    assert out["bundle_id"] == "b-2"


# ---------- async parity for campaign endpoints ---------------------


@respx.mock
async def test_async_start_campaign(async_client: AsyncOrchestratorClient) -> None:
    respx.post(f"{BASE}/campaigns").mock(
        return_value=httpx.Response(
            200,
            json={
                "campaign_id": "c-1",
                "flow_run_id": "f-1",
                "run_count": 4,
                "status": "started",
                "poll": "/campaigns/c-1",
            },
        )
    )
    ack = await async_client.start_campaign(_campaign_create())
    assert ack.campaign_id == "c-1"


@respx.mock
async def test_async_get_campaign_tree(async_client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        return_value=httpx.Response(
            200, json=_tree_payload(status="running", run_ids=["r-1", "r-2"])
        )
    )
    tv = await async_client.get_campaign_tree("c-1")
    assert {r.run_id for r in tv.runs} == {"r-1", "r-2"}


@respx.mock
async def test_async_abort_campaign(async_client: AsyncOrchestratorClient) -> None:
    respx.post(f"{BASE}/campaigns/c-1/abort").mock(
        return_value=httpx.Response(
            200, json={"campaign_id": "c-1", "aborted": True, "flow_run_id": "f-1"}
        )
    )
    ack = await async_client.abort_campaign("c-1")
    assert ack.aborted is True


@respx.mock
async def test_async_verify_campaign_merkle(async_client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/verify-merkle").mock(
        return_value=httpx.Response(
            200,
            json={"campaign_id": "c-1", "valid": True, "status": "ok", "mismatches": []},
        )
    )
    v = await async_client.verify_campaign_merkle("c-1")
    assert v.valid is True


@respx.mock
async def test_async_download_evidence_crate(
    async_client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/campaigns/c-1/evidence.crate.zip").mock(
        return_value=httpx.Response(200, content=b"PK\x03\x04zip")
    )
    blob = await async_client.download_evidence_crate("c-1")
    assert blob == b"PK\x03\x04zip"


# ---------- iter_runs streaming -------------------------------------


@respx.mock
def test_iter_runs_sync_handles_empty_first_poll(
    sync_client: OrchestratorClient,
) -> None:
    """First poll returns empty runs (post-create race), second adds two,
    third reports terminal — generator yields exactly two and stops."""
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        side_effect=[
            httpx.Response(200, json=_tree_payload(status="running", run_ids=[])),
            httpx.Response(
                200, json=_tree_payload(status="running", run_ids=["r-1", "r-2"])
            ),
            httpx.Response(
                200,
                json=_tree_payload(
                    status="completed", run_ids=["r-1", "r-2"], all_completed=True
                ),
            ),
            httpx.Response(
                200,
                json=_tree_payload(
                    status="completed", run_ids=["r-1", "r-2"], all_completed=True
                ),
            ),
        ]
    )
    campaign_obj = Campaign.model_validate(_campaign_record(status="running"))
    runs = list(
        campaign_obj.iter_runs(
            sync_client,
            poll_interval_seconds=0.01,
            max_poll_interval_seconds=0.02,
        )
    )
    assert [r.run_id for r in runs] == ["r-1", "r-2"]


@respx.mock
def test_iter_runs_sync_stops_on_terminal_with_no_new(
    sync_client: OrchestratorClient,
) -> None:
    """Terminal status alone is NOT enough — must also see zero new runs."""
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        side_effect=[
            # Status flips to completed AND runs first appear in same poll —
            # generator must NOT terminate yet (would miss the runs).
            httpx.Response(
                200,
                json=_tree_payload(
                    status="completed", run_ids=["r-1"], all_completed=True
                ),
            ),
            # Next poll: terminal AND zero new runs → terminate.
            httpx.Response(
                200,
                json=_tree_payload(
                    status="completed", run_ids=["r-1"], all_completed=True
                ),
            ),
        ]
    )
    campaign_obj = Campaign.model_validate(_campaign_record(status="running"))
    runs = list(
        campaign_obj.iter_runs(
            sync_client,
            poll_interval_seconds=0.01,
            max_poll_interval_seconds=0.02,
        )
    )
    assert [r.run_id for r in runs] == ["r-1"]


@respx.mock
def test_iter_runs_sync_stops_on_aborted(sync_client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        side_effect=[
            httpx.Response(200, json=_tree_payload(status="running", run_ids=["r-1"])),
            httpx.Response(200, json=_tree_payload(status="aborted", run_ids=["r-1"])),
        ]
    )
    campaign_obj = Campaign.model_validate(_campaign_record(status="running"))
    runs = list(
        campaign_obj.iter_runs(
            sync_client,
            poll_interval_seconds=0.01,
            max_poll_interval_seconds=0.02,
        )
    )
    assert [r.run_id for r in runs] == ["r-1"]


@respx.mock
async def test_iter_runs_async_streams_new_runs(
    async_client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        side_effect=[
            httpx.Response(200, json=_tree_payload(status="running", run_ids=[])),
            httpx.Response(200, json=_tree_payload(status="running", run_ids=["r-1"])),
            httpx.Response(
                200,
                json=_tree_payload(
                    status="completed", run_ids=["r-1", "r-2"], all_completed=True
                ),
            ),
            httpx.Response(
                200,
                json=_tree_payload(
                    status="completed", run_ids=["r-1", "r-2"], all_completed=True
                ),
            ),
        ]
    )
    campaign_obj = Campaign.model_validate(_campaign_record(status="running"))
    seen: list[str] = []
    async for run in campaign_obj.iter_runs(
        async_client,
        poll_interval_seconds=0.01,
        max_poll_interval_seconds=0.02,
    ):
        seen.append(run.run_id)
    assert seen == ["r-1", "r-2"]


@respx.mock
async def test_iter_runs_async_terminates_on_failed(
    async_client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        side_effect=[
            httpx.Response(200, json=_tree_payload(status="failed", run_ids=["r-1"])),
            httpx.Response(200, json=_tree_payload(status="failed", run_ids=["r-1"])),
        ]
    )
    campaign_obj = Campaign.model_validate(_campaign_record(status="running"))
    runs = []
    async for run in campaign_obj.iter_runs(
        async_client,
        poll_interval_seconds=0.01,
        max_poll_interval_seconds=0.02,
    ):
        runs.append(run.run_id)
    assert runs == ["r-1"]


@respx.mock
async def test_iter_runs_async_cancellation_propagates(
    async_client: AsyncOrchestratorClient,
) -> None:
    """asyncio.CancelledError on the consumer must bubble through the generator."""
    respx.get(f"{BASE}/campaigns/c-1/tree").mock(
        return_value=httpx.Response(
            200, json=_tree_payload(status="running", run_ids=["r-1"])
        )
    )
    campaign_obj = Campaign.model_validate(_campaign_record(status="running"))

    async def _consume() -> None:
        async for _ in campaign_obj.iter_runs(
            async_client,
            poll_interval_seconds=0.05,
            max_poll_interval_seconds=0.05,
        ):
            pass

    task = asyncio.create_task(_consume())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
