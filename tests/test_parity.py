"""Parity tests: same expectations for sync + async clients.

Covers methods whose behaviour is identical across the two transports
(everything except the async-only logging or sync-only blocking calls).
Each scenario is parametrized over a sync invoker and an async invoker
so a regression in one client surfaces in both rows of the test report.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
import pytest
import respx

from ai_orchestrator_client import (
    AsyncOrchestratorClient,
    NotFound,
    OrchestratorClient,
    ValidationError,
)
from ai_orchestrator_client.models import OrchestrateRequest

BASE = "http://orchestrator.test"

T = TypeVar("T")


def _run_sync(coro_factory: Callable[[OrchestratorClient], T]) -> T:
    with OrchestratorClient(base_url=BASE) as c:
        return coro_factory(c)


def _run_async(coro_factory: Callable[[AsyncOrchestratorClient], Awaitable[T]]) -> T:
    async def _go() -> T:
        async with AsyncOrchestratorClient(base_url=BASE) as c:
            return await coro_factory(c)

    return asyncio.run(_go())


_INVOKERS = [
    pytest.param("sync", id="sync"),
    pytest.param("async", id="async"),
]


def _invoke(target: str, sync: Callable[[OrchestratorClient], T], async_: Callable[[AsyncOrchestratorClient], Awaitable[T]]) -> T:
    if target == "sync":
        return _run_sync(sync)
    return _run_async(async_)


def _orchestrate_req() -> OrchestrateRequest:
    return OrchestrateRequest(
        project_name="demo",
        prompt="hi",
        planner_model="m",
        generator_models=["m"],
        judge_model="m",
        deploy_target="local",
    )


# ---------- shared scenarios -----------------------------------------


@pytest.mark.parametrize("target", _INVOKERS)
@respx.mock
def test_health_returns_dict(target: str) -> None:
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"orchestrator": {"alive": True}})
    )

    def sync_call(c: OrchestratorClient) -> dict[str, Any]:
        return c.health()

    async def async_call(c: AsyncOrchestratorClient) -> dict[str, Any]:
        return await c.health()

    assert _invoke(target, sync_call, async_call) == {"orchestrator": {"alive": True}}


@pytest.mark.parametrize("target", _INVOKERS)
@respx.mock
def test_run_returns_ack(target: str) -> None:
    respx.post(f"{BASE}/orchestrate").mock(
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

    def sync_call(c: OrchestratorClient) -> str:
        return c.run(_orchestrate_req()).run_id

    async def async_call(c: AsyncOrchestratorClient) -> str:
        ack = await c.run(_orchestrate_req())
        return ack.run_id

    assert _invoke(target, sync_call, async_call) == "r-1"


@pytest.mark.parametrize("target", _INVOKERS)
@respx.mock
def test_404_maps_to_not_found(target: str) -> None:
    respx.get(f"{BASE}/status/missing").mock(
        return_value=httpx.Response(404, json={"detail": "Unknown run_id: missing"})
    )

    def sync_call(c: OrchestratorClient) -> None:
        c.get_status("missing")

    async def async_call(c: AsyncOrchestratorClient) -> None:
        await c.get_status("missing")

    with pytest.raises(NotFound, match="Unknown run_id"):
        _invoke(target, sync_call, async_call)


@pytest.mark.parametrize("target", _INVOKERS)
@respx.mock
def test_422_maps_to_validation_error(target: str) -> None:
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

    def sync_call(c: OrchestratorClient) -> None:
        c.run(_orchestrate_req())

    async def async_call(c: AsyncOrchestratorClient) -> None:
        await c.run(_orchestrate_req())

    with pytest.raises(ValidationError) as info:
        _invoke(target, sync_call, async_call)
    assert info.value.errors[0]["loc"] == ["body", "deploy_target"]
