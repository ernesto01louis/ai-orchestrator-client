"""Tail live log lines for a run via /ws (async).

Usage::

    python examples/stream_logs.py <run_id>

Reads ORCHESTRATOR_URL / ORCHESTRATOR_TOKEN like the other examples.
"""
from __future__ import annotations

import asyncio
import os
import sys

from ai_orchestrator_client import (
    AsyncOrchestratorClient,
    BearerTokenAuth,
    LogEvent,
    StatusEvent,
)


async def main(run_id: str) -> int:
    base_url = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8000")
    token = os.environ.get("ORCHESTRATOR_TOKEN")
    auth = BearerTokenAuth(token) if token else None

    async with AsyncOrchestratorClient(base_url=base_url, auth=auth) as client:
        print(f"-> /ws  (server: {base_url})  run_id={run_id}")
        async for event in client.iter_logs(run_id, include_status=True):
            if isinstance(event, LogEvent):
                print(f"   [{event.phase}] {event.line}")
            elif isinstance(event, StatusEvent):
                print(f"   <status> phase={event.phase}  score={event.score}  completed={event.completed}")
        print("   stream closed (completed=True or server disconnect)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <run_id>", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
