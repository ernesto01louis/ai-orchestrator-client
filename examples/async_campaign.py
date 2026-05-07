"""Submit a campaign and stream new runs as they appear (async).

Demonstrates the empty-``runs[]`` race-guarded ``Campaign.iter_runs``
plus Phase 1.5 Merkle verification at the end. Run with::

    python examples/async_campaign.py
"""
from __future__ import annotations

import asyncio
import os
import sys

from ai_orchestrator_client import (
    AsyncOrchestratorClient,
    BearerTokenAuth,
    CampaignCreate,
    CampaignTemplate,
)


async def main() -> int:
    base_url = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8000")
    token = os.environ.get("ORCHESTRATOR_TOKEN")
    auth = BearerTokenAuth(token) if token else None

    req = CampaignCreate(
        name="sdk-demo-sweep",
        hypothesis="output is invariant across two seeds",
        template=CampaignTemplate(
            project_name="sdk-demo-{seed}",
            prompt="Print 'hello from sdk' (seed {seed}).",
            planner_model="qwen2.5-coder:14b",
            generator_models=["qwen2.5-coder:14b"],
            judge_model="qwen2.5-coder:14b",
            deploy_target="local",
        ),
        params={"seed": [1, 2]},
    )

    async with AsyncOrchestratorClient(base_url=base_url, auth=auth) as client:
        print(f"-> POST /campaigns  (server: {base_url})")
        ack = await client.start_campaign(req)
        print(f"   campaign_id={ack.campaign_id}  run_count={ack.run_count}")

        campaign = await client.get_campaign(ack.campaign_id)
        print("-> streaming runs as they appear:")
        async for run in campaign.iter_runs(
            client, poll_interval_seconds=1.0, max_poll_interval_seconds=5.0
        ):
            print(f"   new: run_id={run.run_id}  params={run.params}  phase={run.phase}")

        verify = await client.verify_campaign_merkle(ack.campaign_id)
        print(f"-> verify_campaign_merkle: valid={verify.valid}  status={verify.status}")
        return 0 if verify.valid else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
