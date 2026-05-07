"""Unit tests for AsyncOrchestratorClient (Phase D).

Mirrors test_sync_client.py — same scenarios, async transport. respx
intercepts httpx.AsyncClient traffic just like the sync side.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import respx

from ai_orchestrator_client import (
    AsyncOrchestratorClient,
    BearerTokenAuth,
    NotFound,
    OrchestrateRequest,
    OrchestratorAPIError,
    RunFailed,
    ServiceUnavailable,
    ValidationError,
    WaitInterrupted,
    WaitTimeout,
)

BASE = "http://orchestrator.test"


@pytest.fixture
async def client() -> AsyncIterator[AsyncOrchestratorClient]:
    async with AsyncOrchestratorClient(base_url=BASE) as c:
        yield c


def _orchestrate_req() -> OrchestrateRequest:
    return OrchestrateRequest(
        project_name="demo",
        prompt="hi",
        planner_model="m",
        generator_models=["m"],
        judge_model="m",
        deploy_target="local",
    )


def _status_body(
    *, phase: str, completed: bool, score: float | None = None, error: str | None = None
) -> dict[str, object]:
    body: dict[str, object] = {
        "run_id": "r-1",
        "phase": phase,
        "score": score,
        "completed": completed,
    }
    if error is not None:
        body["error"] = error
    return body


# ---------- construction + context manager ---------------------------


async def test_async_base_url_strips_trailing_slash() -> None:
    async with AsyncOrchestratorClient(base_url="http://x:8000///") as c:
        assert c._base_url == "http://x:8000"


async def test_async_context_manager_closes_client() -> None:
    c = AsyncOrchestratorClient(base_url=BASE)
    assert not c._http.is_closed
    await c.aclose()
    assert c._http.is_closed


async def test_async_context_manager_via_async_with() -> None:
    async with AsyncOrchestratorClient(base_url=BASE) as c:
        inner = c._http
    assert inner.is_closed


# ---------- health + control + run lifecycle -------------------------


@respx.mock
async def test_async_health(client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"orchestrator": {"alive": True}, "active_runs": 0})
    )
    h = await client.health()
    assert h["orchestrator"]["alive"] is True


@respx.mock
async def test_async_pause_when_running_flips_state(
    client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/control/status").mock(
        return_value=httpx.Response(200, json={"paused": False, "active_runs": 0})
    )
    post = respx.post(f"{BASE}/control/pause").mock(
        return_value=httpx.Response(200, json={"paused": True})
    )
    result = await client.pause()
    assert result == {"paused": True}
    assert post.call_count == 1


@respx.mock
async def test_async_pause_when_already_paused_is_noop(
    client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/control/status").mock(
        return_value=httpx.Response(200, json={"paused": True, "active_runs": 0})
    )
    post = respx.post(f"{BASE}/control/pause").mock(
        return_value=httpx.Response(200, json={"paused": False})
    )
    result = await client.pause()
    assert result["paused"] is True
    assert post.call_count == 0


@respx.mock
async def test_async_resume_when_running_is_noop(
    client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/control/status").mock(
        return_value=httpx.Response(200, json={"paused": False, "active_runs": 0})
    )
    post = respx.post(f"{BASE}/control/pause").mock(
        return_value=httpx.Response(200, json={"paused": True})
    )
    result = await client.resume()
    assert result["paused"] is False
    assert post.call_count == 0


@respx.mock
async def test_async_run_returns_orchestrate_ack(
    client: AsyncOrchestratorClient,
) -> None:
    import json

    route = respx.post(f"{BASE}/orchestrate").mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": "r-1",
                "flow_run_id": "f-1",
                "status": "started",
                "poll": "/status/r-1",
            },
        )
    )
    ack = await client.run(_orchestrate_req())
    assert ack.run_id == "r-1"
    posted = json.loads(route.calls.last.request.read().decode())
    assert posted["project_name"] == "demo"


@respx.mock
async def test_async_get_status_completed(client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": "r-1",
                "phase": "completed",
                "score": 0.91,
                "completed": True,
                "manifest_status": "ok",
                "result": {"score": 0.91},
            },
        )
    )
    s = await client.get_status("r-1")
    assert s.completed is True
    assert s.manifest_status == "ok"


@respx.mock
async def test_async_get_result(client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/result/r-1").mock(
        return_value=httpx.Response(200, json={"score": 0.91})
    )
    r = await client.get_result("r-1")
    assert r == {"score": 0.91}


@respx.mock
async def test_async_verify_run(client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/runs/r-1/verify").mock(
        return_value=httpx.Response(
            200,
            json={"run_id": "r-1", "valid": True, "status": "ok", "mismatches": []},
        )
    )
    v = await client.verify_run("r-1")
    assert v.valid is True


@respx.mock
async def test_async_tail_log(client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/logs/r-1/tail").mock(
        return_value=httpx.Response(200, text="line 1\nline 2\n")
    )
    assert (await client.tail_log("r-1")) == "line 1\nline 2\n"


# ---------- error mapping --------------------------------------------


@respx.mock
async def test_async_404_raises_not_found(client: AsyncOrchestratorClient) -> None:
    respx.get(f"{BASE}/status/missing").mock(
        return_value=httpx.Response(404, json={"detail": "Unknown run_id"})
    )
    with pytest.raises(NotFound):
        await client.get_status("missing")


@respx.mock
async def test_async_503_raises_service_unavailable(
    client: AsyncOrchestratorClient,
) -> None:
    respx.post(f"{BASE}/orchestrate").mock(
        return_value=httpx.Response(503, json={"detail": "Orchestrator is paused"})
    )
    with pytest.raises(ServiceUnavailable):
        await client.run(_orchestrate_req())


@respx.mock
async def test_async_422_raises_validation_error(
    client: AsyncOrchestratorClient,
) -> None:
    respx.post(f"{BASE}/orchestrate").mock(
        return_value=httpx.Response(
            422,
            json={
                "detail": [
                    {
                        "loc": ["body", "deploy_target"],
                        "msg": "field required",
                        "type": "value_error.missing",
                    }
                ]
            },
        )
    )
    with pytest.raises(ValidationError) as info:
        await client.run(_orchestrate_req())
    assert info.value.errors[0]["loc"] == ["body", "deploy_target"]


@respx.mock
async def test_async_500_raises_generic_api_error(
    client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(OrchestratorAPIError) as info:
        await client.health()
    assert info.value.status_code == 500


# ---------- wait_for_completion --------------------------------------


@respx.mock
async def test_async_wait_for_completion_polls_until_done(
    client: AsyncOrchestratorClient,
) -> None:
    route = respx.get(f"{BASE}/status/r-1").mock(
        side_effect=[
            httpx.Response(200, json=_status_body(phase="planning", completed=False)),
            httpx.Response(200, json=_status_body(phase="executing", completed=False)),
            httpx.Response(200, json=_status_body(phase="completed", completed=True, score=0.5)),
        ]
    )
    final = await client.wait_for_completion(
        "r-1", timeout=2.0, poll_interval=0.01, max_poll_interval=0.05
    )
    assert final.completed is True
    assert route.call_count == 3


@respx.mock
async def test_async_wait_for_completion_phase_flap_doesnt_terminate(
    client: AsyncOrchestratorClient,
) -> None:
    route = respx.get(f"{BASE}/status/r-1").mock(
        side_effect=[
            httpx.Response(200, json=_status_body(phase="executing", completed=False)),
            httpx.Response(200, json=_status_body(phase="executing", completed=False)),
            httpx.Response(200, json=_status_body(phase="completed", completed=True)),
        ]
    )
    final = await client.wait_for_completion(
        "r-1", timeout=2.0, poll_interval=0.01, max_poll_interval=0.05
    )
    assert final.completed is True
    assert route.call_count == 3


@respx.mock
async def test_async_wait_for_completion_timeout(
    client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200, json=_status_body(phase="executing", completed=False)
        )
    )
    with pytest.raises(WaitTimeout) as info:
        await client.wait_for_completion(
            "r-1", timeout=0.05, poll_interval=0.01, max_poll_interval=0.02
        )
    assert info.value.last_phase == "executing"


@respx.mock
async def test_async_wait_for_completion_run_failed(
    client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200,
            json=_status_body(
                phase="failed", completed=True, error="planner returned no plan"
            ),
        )
    )
    with pytest.raises(RunFailed) as info:
        await client.wait_for_completion("r-1", timeout=1.0, poll_interval=0.01)
    assert "planner" in info.value.error


@respx.mock
async def test_async_wait_for_completion_stop_event_interrupts(
    client: AsyncOrchestratorClient,
) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200, json=_status_body(phase="executing", completed=False)
        )
    )
    stop = asyncio.Event()

    async def _trip_after_first_poll() -> None:
        await asyncio.sleep(0.02)
        stop.set()

    asyncio.create_task(_trip_after_first_poll())
    with pytest.raises(WaitInterrupted) as info:
        await client.wait_for_completion(
            "r-1",
            timeout=5.0,
            poll_interval=0.05,
            max_poll_interval=0.05,
            stop_event=stop,
        )
    assert info.value.run_id == "r-1"


@respx.mock
async def test_async_wait_for_completion_cancellation_propagates(
    client: AsyncOrchestratorClient,
) -> None:
    """asyncio.CancelledError must escape (no swallowing)."""
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200, json=_status_body(phase="executing", completed=False)
        )
    )

    async def _wait() -> None:
        await client.wait_for_completion(
            "r-1", timeout=10.0, poll_interval=0.05, max_poll_interval=0.05
        )

    task = asyncio.create_task(_wait())
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ---------- auth -----------------------------------------------------


@respx.mock
async def test_async_bearer_auth_header_injected() -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={})
    )
    async with AsyncOrchestratorClient(
        base_url=BASE, auth=BearerTokenAuth("sek-ret")
    ) as c:
        await c.health()
    assert route.calls.last.request.headers.get("authorization") == "Bearer sek-ret"


@respx.mock
async def test_async_auth_headers_refreshed_per_request() -> None:
    class RotatingAuth:
        def __init__(self) -> None:
            self.calls = 0

        def get_headers(self) -> dict[str, str]:
            self.calls += 1
            return {"Authorization": f"Bearer t-{self.calls}"}

    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={})
    )
    auth = RotatingAuth()
    async with AsyncOrchestratorClient(base_url=BASE, auth=auth) as c:
        await c.health()
        await c.health()
    assert route.calls[0].request.headers["authorization"] == "Bearer t-1"
    assert route.calls[1].request.headers["authorization"] == "Bearer t-2"


@respx.mock
async def test_async_user_agent_includes_version() -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={})
    )
    async with AsyncOrchestratorClient(base_url=BASE) as c:
        await c.health()
    ua = route.calls.last.request.headers["user-agent"]
    assert ua.startswith("ai-orchestrator-client/")
