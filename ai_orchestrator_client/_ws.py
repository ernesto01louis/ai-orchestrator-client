"""WebSocket transport helper for live /ws streaming (Phase F).

The server's ``/ws`` endpoint broadcasts run-level log lines and status
updates to every connected client (no per-run subscription). This
helper connects, filters by ``run_id``, parses each frame into a typed
:class:`LogEvent` or :class:`StatusEvent`, and yields them.

Keep-alive: the ``websockets`` library auto-emits WS protocol-level
pings every 20s by default, which the orchestrator's WebSocket library
honours independently of the text heartbeat path documented in
``api/routes.py:1901-1920``. We do not need to send anything; just
receive.

Reconnect policy: a single retry on :class:`ConnectionClosed` so a
transient server restart doesn't drop the consumer mid-run. The second
close propagates so callers can decide what to do.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

from .models.events import LogEvent, StatusEvent

log = logging.getLogger(__name__)

DEFAULT_RECONNECT_BACKOFF_SECONDS = 1.0


def _http_to_ws(base_url: str) -> str:
    """``http(s)://host`` → ``ws(s)://host``."""
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :]
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :]
    raise ValueError(f"base_url must start with http:// or https://, got {base_url!r}")


async def stream_ws_events(
    base_url: str,
    *,
    run_id: str,
    auth_headers: dict[str, str] | None = None,
    include_status: bool = False,
    reconnect_once: bool = True,
    reconnect_backoff_seconds: float = DEFAULT_RECONNECT_BACKOFF_SECONDS,
) -> AsyncIterator[LogEvent | StatusEvent]:
    """Yield typed events from /ws filtered by ``run_id``.

    Iteration terminates on the first ``StatusEvent`` with
    ``completed=True`` (regardless of ``include_status``) so callers
    can use this to drive completion in a streaming fashion. Otherwise
    iteration ends when the server closes the connection cleanly.

    The orchestrator's /ws broadcasts globally (no per-run subscription
    on the wire), so this helper filters client-side. Traffic for
    unrelated runs still reaches the SDK and is silently discarded —
    for high-volume deployments prefer ``get_status()`` polling plus
    ``tail_log()``.

    On reconnect (``reconnect_once=True``), the server does NOT replay
    broadcast history: events that fired during the disconnect window
    are lost. The SDK does not deduplicate either, so a server that
    chooses to replay (or a test harness) may produce duplicates.
    """
    ws_url = _http_to_ws(base_url) + "/ws"
    headers = dict(auth_headers or {})

    attempts = 2 if reconnect_once else 1
    for attempt in range(attempts):
        try:
            async for event in _consume_once(
                ws_url=ws_url,
                headers=headers,
                run_id=run_id,
                include_status=include_status,
            ):
                yield event
            return  # graceful server close — stop iteration
        except ConnectionClosed:
            if attempt + 1 == attempts:
                raise
            log.warning("ws closed; reconnecting once after %ss", reconnect_backoff_seconds)
            await asyncio.sleep(reconnect_backoff_seconds)


async def _consume_once(
    *,
    ws_url: str,
    headers: dict[str, str],
    run_id: str,
    include_status: bool,
) -> AsyncIterator[LogEvent | StatusEvent]:
    async with ws_connect(ws_url, additional_headers=headers) as ws:
        async for raw in ws:
            try:
                msg = json.loads(raw if isinstance(raw, str) else raw.decode())
            except (TypeError, ValueError):
                continue
            if not isinstance(msg, dict):
                continue
            typ = msg.get("type")
            if typ == "pong":
                continue  # heartbeat — skip silently
            if msg.get("run_id") != run_id:
                continue
            if typ == "log":
                yield LogEvent.model_validate(msg)
            elif typ == "status":
                event = StatusEvent.model_validate(msg)
                if include_status:
                    yield event
                if event.completed:
                    return
            # Unknown types are silently ignored — server may add new
            # broadcast shapes that older clients should not crash on.
