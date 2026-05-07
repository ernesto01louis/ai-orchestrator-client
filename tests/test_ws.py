"""Phase F coverage: async WS log streaming via in-process websockets.serve.

A tiny test-local server mimics the orchestrator's /ws shape: emits a
canned list of frames then closes. The SDK consumes via
``AsyncOrchestratorClient.iter_logs(run_id, ...)`` and we assert the
filter / terminator / reconnect / auth-header behavior.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from websockets.asyncio.server import Server, ServerConnection
from websockets.asyncio.server import serve as ws_serve
from websockets.exceptions import ConnectionClosed

from ai_orchestrator_client import (
    AsyncOrchestratorClient,
    BearerTokenAuth,
    LogEvent,
    StatusEvent,
)


def _log(run_id: str, line: str, phase: str = "executing") -> dict[str, Any]:
    return {"type": "log", "run_id": run_id, "line": line, "phase": phase}


def _status(
    run_id: str,
    *,
    phase: str = "executing",
    score: float | None = None,
    completed: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "status",
        "run_id": run_id,
        "phase": phase,
        "score": score,
        "completed": completed,
        "error": error,
        "project": "demo",
        "target": "local",
    }


async def _spawn_canned_server(
    frames: list[dict[str, Any]],
    *,
    captured_headers: list[dict[str, str]] | None = None,
    drop_first_connection: bool = False,
    delay_per_frame_seconds: float = 0.0,
) -> tuple[Server, str]:
    """Start ws://127.0.0.1:<random> serving the canned ``frames`` once.

    If ``drop_first_connection`` is True the first connection closes
    abruptly after one frame; the second sees the full sequence (used to
    test the SDK's reconnect-once policy).
    """
    state = {"connections": 0}

    async def handler(ws: ServerConnection) -> None:
        state["connections"] += 1
        if captured_headers is not None:
            captured_headers.append(dict(ws.request.headers) if ws.request else {})
        if drop_first_connection and state["connections"] == 1:
            await ws.send(json.dumps(frames[0]))
            await ws.close(code=1011, reason="server hiccup")
            return
        for frame in frames:
            if delay_per_frame_seconds:
                await asyncio.sleep(delay_per_frame_seconds)
            await ws.send(json.dumps(frame))
        await ws.close()

    server = await ws_serve(handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    port = sock.getsockname()[1]
    return server, f"http://127.0.0.1:{port}"


@pytest.fixture
async def client() -> AsyncIterator[AsyncOrchestratorClient]:
    # Real base_url is reset per test inside via _spawn_canned_server.
    async with AsyncOrchestratorClient(base_url="http://placeholder.test") as c:
        yield c


# ---------- filter + terminator --------------------------------------


async def test_iter_logs_filters_by_run_id() -> None:
    server, base_url = await _spawn_canned_server(
        [
            _log("r-1", "line A"),
            _log("r-2", "OTHER RUN — should be skipped"),
            _log("r-1", "line B"),
            _status("r-1", phase="completed", score=0.5, completed=True),
        ]
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            events = []
            async for ev in c.iter_logs("r-1"):
                events.append(ev)
        assert all(isinstance(ev, LogEvent) for ev in events)
        assert [ev.line for ev in cast(list[LogEvent], events)] == ["line A", "line B"]
    finally:
        server.close()
        await server.wait_closed()


async def test_iter_logs_terminates_on_completed_status() -> None:
    server, base_url = await _spawn_canned_server(
        [
            _log("r-1", "starting"),
            _status("r-1", phase="completed", completed=True),
            _log("r-1", "AFTER TERMINAL — must not be yielded"),
        ]
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            events = [ev async for ev in c.iter_logs("r-1")]
        assert len(events) == 1
        assert isinstance(events[0], LogEvent)
        assert events[0].line == "starting"
    finally:
        server.close()
        await server.wait_closed()


async def test_iter_logs_include_status_yields_both() -> None:
    server, base_url = await _spawn_canned_server(
        [
            _log("r-1", "starting"),
            _status("r-1", phase="executing", completed=False),
            _log("r-1", "midway"),
            _status("r-1", phase="completed", completed=True),
        ]
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            events = [ev async for ev in c.iter_logs("r-1", include_status=True)]
        types = [type(ev).__name__ for ev in events]
        assert types == ["LogEvent", "StatusEvent", "LogEvent", "StatusEvent"]
        assert isinstance(events[-1], StatusEvent)
        assert events[-1].completed is True
    finally:
        server.close()
        await server.wait_closed()


async def test_iter_logs_skips_pong_heartbeat() -> None:
    server, base_url = await _spawn_canned_server(
        [
            {"type": "pong"},
            _log("r-1", "after pong"),
            _status("r-1", phase="completed", completed=True),
        ]
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            events = [ev async for ev in c.iter_logs("r-1")]
        assert len(events) == 1
        assert isinstance(events[0], LogEvent)
        assert events[0].line == "after pong"
    finally:
        server.close()
        await server.wait_closed()


async def test_iter_logs_skips_unknown_message_types() -> None:
    server, base_url = await _spawn_canned_server(
        [
            {"type": "future-broadcast", "run_id": "r-1", "payload": 42},
            _log("r-1", "still here"),
            _status("r-1", phase="completed", completed=True),
        ]
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            events = [ev async for ev in c.iter_logs("r-1")]
        assert len(events) == 1
        assert events[0].line == "still here"
    finally:
        server.close()
        await server.wait_closed()


# ---------- reconnect-on-close ---------------------------------------


async def test_iter_logs_reconnects_once_on_close() -> None:
    server, base_url = await _spawn_canned_server(
        [
            _log("r-1", "before drop"),
            _log("r-1", "after reconnect"),
            _status("r-1", phase="completed", completed=True),
        ],
        drop_first_connection=True,
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            events = [ev async for ev in c.iter_logs("r-1")]
        assert [ev.line for ev in cast(list[LogEvent], events)] == [
            "before drop",
            "before drop",  # served again from the start by the test server
            "after reconnect",
        ]
    finally:
        server.close()
        await server.wait_closed()


async def test_iter_logs_no_reconnect_when_disabled() -> None:
    server, base_url = await _spawn_canned_server(
        [_log("r-1", "before drop")],
        drop_first_connection=True,
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            with pytest.raises(ConnectionClosed):
                async for _ in c.iter_logs("r-1", reconnect_once=False):
                    pass
    finally:
        server.close()
        await server.wait_closed()


# ---------- auth header propagation ----------------------------------


async def test_iter_logs_auth_headers_propagated() -> None:
    captured: list[dict[str, str]] = []
    server, base_url = await _spawn_canned_server(
        [_status("r-1", phase="completed", completed=True)],
        captured_headers=captured,
    )
    try:
        async with AsyncOrchestratorClient(
            base_url=base_url, auth=BearerTokenAuth("sek-ret")
        ) as c:
            async for _ in c.iter_logs("r-1"):
                pass
        assert captured, "server did not record any handshake headers"
        # websockets normalizes header names to title-case strings.
        headers = {k.lower(): v for k, v in captured[0].items()}
        assert headers["authorization"] == "Bearer sek-ret"
    finally:
        server.close()
        await server.wait_closed()


# ---------- consumer-break + cancellation ---------------------------


async def test_iter_logs_consumer_break_closes_cleanly() -> None:
    server, base_url = await _spawn_canned_server(
        [
            _log("r-1", "first"),
            _log("r-1", "second"),
            _log("r-1", "third"),
            _status("r-1", phase="completed", completed=True),
        ]
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            collected = []
            async for ev in c.iter_logs("r-1"):
                collected.append(ev)
                if len(collected) == 1:
                    break
        # Async with on the test server below already cleaned up; assert
        # we got exactly the first event with no resource leaks.
        assert len(collected) == 1
        assert isinstance(collected[0], LogEvent)
    finally:
        server.close()
        await server.wait_closed()


async def test_iter_logs_cancellation_propagates() -> None:
    server, base_url = await _spawn_canned_server(
        [
            _log("r-1", "first"),
            # No terminal status — server stays open, client must be
            # cancellable.
        ],
        delay_per_frame_seconds=0.5,
    )
    try:
        async with AsyncOrchestratorClient(base_url=base_url) as c:
            async def _consume() -> None:
                async for _ in c.iter_logs("r-1"):
                    pass

            task = asyncio.create_task(_consume())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        server.close()
        await server.wait_closed()


# ---------- _http_to_ws unit ----------------------------------------


def test_http_to_ws_conversion() -> None:
    from ai_orchestrator_client._ws import _http_to_ws

    assert _http_to_ws("http://x:8000") == "ws://x:8000"
    assert _http_to_ws("https://x:8000") == "wss://x:8000"
    with pytest.raises(ValueError, match="must start with"):
        _http_to_ws("ftp://nope")
