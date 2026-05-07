"""Unit tests for the sync OrchestratorClient (Phase C).

All HTTP traffic is intercepted by respx; no real orchestrator is
needed. Each test mocks only the routes it cares about.
"""
from __future__ import annotations

import threading
from collections.abc import Iterator

import httpx
import pytest
import respx

from ai_orchestrator_client import (
    BearerTokenAuth,
    NotFound,
    OrchestrateRequest,
    OrchestratorAPIError,
    OrchestratorClient,
    RunFailed,
    ServiceUnavailable,
    ValidationError,
    WaitInterrupted,
    WaitTimeout,
)

BASE = "http://orchestrator.test"


@pytest.fixture
def client() -> Iterator[OrchestratorClient]:
    with OrchestratorClient(base_url=BASE) as c:
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


# ---------- construction + base_url + context manager -----------------


def test_base_url_strips_trailing_slash() -> None:
    with OrchestratorClient(base_url="http://x:8000///") as c:
        assert c._base_url == "http://x:8000"


def test_context_manager_closes_underlying_client() -> None:
    c = OrchestratorClient(base_url=BASE)
    assert not c._http.is_closed
    c.close()
    assert c._http.is_closed


def test_context_manager_via_with_block() -> None:
    with OrchestratorClient(base_url=BASE) as c:
        inner = c._http
    assert inner.is_closed


# ---------- health + control -----------------------------------------


@respx.mock
def test_health(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"orchestrator": {"alive": True}, "active_runs": 0})
    )
    h = client.health()
    assert h["orchestrator"]["alive"] is True
    assert h["active_runs"] == 0


@respx.mock
def test_pause_when_running_flips_state(client: OrchestratorClient) -> None:
    """pause() guards the toggle endpoint by checking /control/status first."""
    respx.get(f"{BASE}/control/status").mock(
        return_value=httpx.Response(200, json={"paused": False, "active_runs": 0})
    )
    post = respx.post(f"{BASE}/control/pause").mock(
        return_value=httpx.Response(200, json={"paused": True})
    )
    assert client.pause() == {"paused": True}
    assert post.call_count == 1


@respx.mock
def test_pause_when_already_paused_is_noop(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/control/status").mock(
        return_value=httpx.Response(200, json={"paused": True, "active_runs": 0})
    )
    post = respx.post(f"{BASE}/control/pause").mock(
        return_value=httpx.Response(200, json={"paused": False})
    )
    result = client.pause()
    assert result["paused"] is True
    assert post.call_count == 0


@respx.mock
def test_resume_when_paused_flips_state(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/control/status").mock(
        return_value=httpx.Response(200, json={"paused": True, "active_runs": 0})
    )
    post = respx.post(f"{BASE}/control/pause").mock(
        return_value=httpx.Response(200, json={"paused": False})
    )
    assert client.resume() == {"paused": False}
    assert post.call_count == 1


@respx.mock
def test_resume_when_already_running_is_noop(client: OrchestratorClient) -> None:
    """Toggle-endpoint footgun guard — resume() must not pause a running server."""
    respx.get(f"{BASE}/control/status").mock(
        return_value=httpx.Response(200, json={"paused": False, "active_runs": 0})
    )
    post = respx.post(f"{BASE}/control/pause").mock(
        return_value=httpx.Response(200, json={"paused": True})
    )
    result = client.resume()
    assert result["paused"] is False
    assert post.call_count == 0


@respx.mock
def test_restart(client: OrchestratorClient) -> None:
    respx.post(f"{BASE}/control/restart").mock(
        return_value=httpx.Response(200, json={"status": "restarting"})
    )
    assert client.restart()["status"] == "restarting"


# ---------- run lifecycle --------------------------------------------


@respx.mock
def test_run_returns_orchestrate_ack(client: OrchestratorClient) -> None:
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
    ack = client.run(_orchestrate_req())
    assert ack.run_id == "r-1"
    assert ack.flow_run_id == "f-1"
    assert route.call_count == 1
    posted = json.loads(route.calls.last.request.read().decode())
    assert posted["project_name"] == "demo"
    assert posted["prompt"] == "hi"
    assert posted["planner_model"] == "m"
    assert posted["generator_models"] == ["m"]
    assert posted["judge_model"] == "m"
    assert posted["deploy_target"] == "local"
    # Optional Nones round-trip explicitly so the server sees a flat shape.
    assert posted["max_iterations"] is None
    assert posted["reference_files"] is None


@respx.mock
def test_get_status_running(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": "r-1",
                "phase": "executing",
                "score": None,
                "completed": False,
                "manifest_status": None,
            },
        )
    )
    s = client.get_status("r-1")
    assert s.completed is False
    assert s.error is None
    assert s.manifest_status is None


@respx.mock
def test_get_status_completed(client: OrchestratorClient) -> None:
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
    s = client.get_status("r-1")
    assert s.completed is True
    assert s.manifest_status == "ok"
    assert s.result == {"score": 0.91}


@respx.mock
def test_get_status_404_raises_not_found(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/status/missing").mock(
        return_value=httpx.Response(404, json={"detail": "Unknown run_id: missing"})
    )
    with pytest.raises(NotFound, match="Unknown run_id"):
        client.get_status("missing")


@respx.mock
def test_503_raises_service_unavailable(client: OrchestratorClient) -> None:
    respx.post(f"{BASE}/orchestrate").mock(
        return_value=httpx.Response(503, json={"detail": "Orchestrator is paused"})
    )
    with pytest.raises(ServiceUnavailable, match="paused"):
        client.run(_orchestrate_req())


@respx.mock
def test_500_raises_generic_api_error(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/health").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(OrchestratorAPIError) as info:
        client.health()
    assert info.value.status_code == 500


@respx.mock
def test_422_raises_validation_error_with_structured_detail(
    client: OrchestratorClient,
) -> None:
    """FastAPI 422 detail is a list of {loc, msg, type}; preserved on body."""
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
        client.run(_orchestrate_req())
    assert info.value.status_code == 422
    assert "deploy_target" in str(info.value)
    assert info.value.errors == [
        {
            "loc": ["body", "deploy_target"],
            "msg": "field required",
            "type": "value_error.missing",
        }
    ]


def test_closed_client_reuse_raises() -> None:
    c = OrchestratorClient(base_url=BASE)
    c.close()
    with pytest.raises(RuntimeError, match=r"closed"):
        c.health()


@respx.mock
def test_get_result_returns_raw_dict(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/result/r-1").mock(
        return_value=httpx.Response(200, json={"score": 0.91, "code": "print('hi')"})
    )
    r = client.get_result("r-1")
    assert r == {"score": 0.91, "code": "print('hi')"}


@respx.mock
def test_verify_run(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/runs/r-1/verify").mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": "r-1",
                "valid": True,
                "status": "ok",
                "mismatches": [],
            },
        )
    )
    v = client.verify_run("r-1")
    assert v.valid is True
    assert v.status == "ok"


@respx.mock
def test_verify_run_corrupted(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/runs/r-1/verify").mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": "r-1",
                "valid": False,
                "status": "corrupted",
                "mismatches": ["sha256 mismatch on artifacts/output.json"],
            },
        )
    )
    v = client.verify_run("r-1")
    assert v.valid is False
    assert v.mismatches == ["sha256 mismatch on artifacts/output.json"]


@respx.mock
def test_tail_log(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/logs/r-1/tail").mock(
        return_value=httpx.Response(200, text="line 1\nline 2\n")
    )
    assert client.tail_log("r-1") == "line 1\nline 2\n"


# ---------- wait_for_completion --------------------------------------


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


@respx.mock
def test_wait_for_completion_polls_until_done(client: OrchestratorClient) -> None:
    route = respx.get(f"{BASE}/status/r-1").mock(
        side_effect=[
            httpx.Response(200, json=_status_body(phase="planning", completed=False)),
            httpx.Response(200, json=_status_body(phase="executing", completed=False)),
            httpx.Response(200, json=_status_body(phase="completed", completed=True, score=0.5)),
        ]
    )
    final = client.wait_for_completion(
        "r-1",
        timeout=2.0,
        poll_interval=0.01,
        max_poll_interval=0.05,
    )
    assert final.completed is True
    assert final.score == 0.5
    assert route.call_count == 3


@respx.mock
def test_wait_for_completion_phase_flap_doesnt_terminate(
    client: OrchestratorClient,
) -> None:
    """Prefect task retry: phase repeats, ``completed`` is the only oracle."""
    route = respx.get(f"{BASE}/status/r-1").mock(
        side_effect=[
            httpx.Response(200, json=_status_body(phase="executing", completed=False)),
            httpx.Response(200, json=_status_body(phase="executing", completed=False)),
            httpx.Response(200, json=_status_body(phase="executing", completed=False)),
            httpx.Response(200, json=_status_body(phase="completed", completed=True)),
        ]
    )
    final = client.wait_for_completion(
        "r-1", timeout=2.0, poll_interval=0.01, max_poll_interval=0.05
    )
    assert final.completed is True
    assert route.call_count == 4


@respx.mock
def test_wait_for_completion_timeout(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200, json=_status_body(phase="executing", completed=False)
        )
    )
    with pytest.raises(WaitTimeout) as info:
        client.wait_for_completion(
            "r-1", timeout=0.05, poll_interval=0.01, max_poll_interval=0.02
        )
    assert info.value.run_id == "r-1"
    assert info.value.last_phase == "executing"


@respx.mock
def test_wait_for_completion_run_failed(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200,
            json=_status_body(
                phase="failed", completed=True, error="planner returned no plan"
            ),
        )
    )
    with pytest.raises(RunFailed) as info:
        client.wait_for_completion(
            "r-1", timeout=1.0, poll_interval=0.01
        )
    assert info.value.run_id == "r-1"
    assert "planner" in info.value.error


@respx.mock
def test_wait_for_completion_stop_event(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/status/r-1").mock(
        return_value=httpx.Response(
            200, json=_status_body(phase="executing", completed=False)
        )
    )
    stop = threading.Event()

    def _trip_stop() -> None:
        # Set the event after a short delay so the first poll happens first.
        threading.Timer(0.02, stop.set).start()

    _trip_stop()
    with pytest.raises(WaitInterrupted) as info:
        client.wait_for_completion(
            "r-1",
            timeout=5.0,
            poll_interval=0.05,
            max_poll_interval=0.05,
            stop_event=stop,
        )
    assert info.value.run_id == "r-1"


# ---------- auth -----------------------------------------------------


@respx.mock
def test_bearer_auth_header_injected() -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={})
    )
    with OrchestratorClient(base_url=BASE, auth=BearerTokenAuth("sek-ret")) as c:
        c.health()
    sent = route.calls.last.request.headers.get("authorization")
    assert sent == "Bearer sek-ret"


@respx.mock
def test_no_auth_no_authorization_header() -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={})
    )
    with OrchestratorClient(base_url=BASE) as c:
        c.health()
    assert "authorization" not in route.calls.last.request.headers


def test_bearer_token_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        BearerTokenAuth("")


@respx.mock
def test_user_agent_header_includes_version() -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={})
    )
    with OrchestratorClient(base_url=BASE) as c:
        c.health()
    ua = route.calls.last.request.headers["user-agent"]
    assert ua.startswith("ai-orchestrator-client/")
    # Version is appended after the slash; format-validate the rest.
    _, _, ver = ua.partition("/")
    assert ver and "." in ver


@respx.mock
def test_auth_headers_refreshed_per_request() -> None:
    """Token-rotating AuthProvider must hit the wire fresh each call."""

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
    with OrchestratorClient(base_url=BASE, auth=auth) as c:
        c.health()
        c.health()
    assert route.calls[0].request.headers["authorization"] == "Bearer t-1"
    assert route.calls[1].request.headers["authorization"] == "Bearer t-2"
    assert auth.calls == 2
