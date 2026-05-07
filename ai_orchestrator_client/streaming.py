"""Polling-based streaming helpers for ``Campaign.iter_runs``.

Implementation lives outside ``models/`` to keep the Pydantic model
package free of client/transport imports — the ``Campaign.iter_runs``
method dispatches into the helpers here at call time so the dependency
arrow stays one-way.

Termination rule (handles the empty-``runs[]`` race documented at
``api/routes.py:2050-2105``): keep polling while either

  - the campaign hasn't reached a terminal status, OR
  - the most recent poll yielded at least one *new* run id.

Without the second clause we'd terminate on the *same* poll where the
last batch of runs first appears alongside ``status="completed"``.

Server contract (``orchestration/campaign.py`` Phase 1.3): the campaign
status only flips to a terminal value AFTER all child subflows have
returned, so a "stragglers after terminal" scenario is impossible.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

from ._base import (
    DEFAULT_MAX_POLL_INTERVAL_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
)
from .models.campaign import CampaignTreeRun

if TYPE_CHECKING:
    from .async_client import AsyncOrchestratorClient
    from .sync_client import OrchestratorClient

_TERMINAL_STATUSES = frozenset({"completed", "aborted", "failed"})


def _iter_runs_sync(
    client: OrchestratorClient,
    campaign_id: str,
    *,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_poll_interval_seconds: float = DEFAULT_MAX_POLL_INTERVAL_SECONDS,
) -> Iterator[CampaignTreeRun]:
    seen: set[str] = set()
    interval = poll_interval_seconds

    while True:
        tree = client.get_campaign_tree(campaign_id)
        new_runs = [r for r in tree.runs if r.run_id not in seen]
        for run in new_runs:
            seen.add(run.run_id)
            yield run

        if tree.campaign.status in _TERMINAL_STATUSES and not new_runs:
            return

        time.sleep(interval)
        interval = min(interval * 1.5, max_poll_interval_seconds)


async def _iter_runs_async(
    client: AsyncOrchestratorClient,
    campaign_id: str,
    *,
    poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_poll_interval_seconds: float = DEFAULT_MAX_POLL_INTERVAL_SECONDS,
) -> AsyncIterator[CampaignTreeRun]:
    seen: set[str] = set()
    interval = poll_interval_seconds

    while True:
        tree = await client.get_campaign_tree(campaign_id)
        new_runs = [r for r in tree.runs if r.run_id not in seen]
        for run in new_runs:
            seen.add(run.run_id)
            yield run

        if tree.campaign.status in _TERMINAL_STATUSES and not new_runs:
            return

        await asyncio.sleep(interval)
        interval = min(interval * 1.5, max_poll_interval_seconds)
