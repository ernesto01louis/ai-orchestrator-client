# Quickstart

Five-minute path from `pip install` to a verified run.

## 0. Prerequisites

- An AI Orchestrator instance reachable from your network. Default
  install runs on `http://localhost:8000` (LXC at `192.168.2.219:8000`
  in the homelab reference deployment).
- Python 3.11+.

## 1. Install

```bash
# Pre-release — `--pre` is required until 0.1.0 final ships.
pip install --pre ai-orchestrator-client
```

## 2. Submit a run

```python
from ai_orchestrator_client import OrchestrateRequest, OrchestratorClient

req = OrchestrateRequest(
    project_name="hello",
    prompt="Print 'hello' from a Python script.",
    planner_model="qwen2.5-coder:14b",
    generator_models=["qwen2.5-coder:14b"],
    judge_model="qwen2.5-coder:14b",
    deploy_target="local",
)

with OrchestratorClient(base_url="http://localhost:8000") as c:
    ack = c.run(req)
    final = c.wait_for_completion(ack.run_id, timeout=600)
    verify = c.verify_run(ack.run_id)
    print(final.score, "manifest:", verify.status)
```

`wait_for_completion` polls `/status/{run_id}` with a 1.5× backoff up
to 5 s, returning the final `RunStatus` when `completed=True`. If the
run reports an error, it raises `RunFailed` so callers don't have to
inspect `.error` themselves.

## 3. Submit a campaign and stream

```python
import asyncio
from ai_orchestrator_client import (
    AsyncOrchestratorClient, CampaignCreate, CampaignTemplate,
)

async def main():
    req = CampaignCreate(
        name="seed-sweep",
        hypothesis="hello-world output is invariant across seeds",
        template=CampaignTemplate(
            project_name="hello-{seed}",
            prompt="Print 'hello {seed}'.",
            planner_model="qwen2.5-coder:14b",
            generator_models=["qwen2.5-coder:14b"],
            judge_model="qwen2.5-coder:14b",
            deploy_target="local",
        ),
        params={"seed": [1, 2, 3]},
    )
    async with AsyncOrchestratorClient(base_url="http://localhost:8000") as c:
        ack = await c.start_campaign(req)
        campaign = await c.get_campaign(ack.campaign_id)
        async for run in campaign.iter_runs(c):
            print("run appeared:", run.run_id)
        v = await c.verify_campaign_merkle(ack.campaign_id)
        print("merkle ok?", v.valid)

asyncio.run(main())
```

`Campaign.iter_runs(client)` polls `/campaigns/{id}/tree`, yielding each
`CampaignTreeRun` the first time it appears. It correctly handles the
post-create race where the campaign record exists but `runs[]` is still
empty for a beat or two while the runner thread expands the parameter
grid.

## 4. Tail logs

```python
async with AsyncOrchestratorClient(...) as c:
    async for ev in c.iter_logs("run-uuid", include_status=True):
        print(ev)
```

`iter_logs` connects to `/ws`, filters frames by `run_id`, and
terminates on the first `StatusEvent` with `completed=True`.

## 5. Auth

```python
from ai_orchestrator_client import BearerTokenAuth, OrchestratorClient
client = OrchestratorClient(base_url=..., auth=BearerTokenAuth(token))
```

The header is sent on every HTTP and WS request. The Phase 1.6
orchestrator ignores it (no server-side auth yet); Phase 1.7 will
honor it without an SDK change. Token-rotating `AuthProvider`
implementations are called fresh per request.

## 6. Errors

```python
from ai_orchestrator_client import (
    OrchestratorError, RunFailed, ValidationError, WaitTimeout,
)

try:
    final = client.wait_for_completion(run_id, timeout=600)
except RunFailed as exc:
    print("run failed:", exc.error)
except WaitTimeout as exc:
    print("timeout, last phase:", exc.last_phase)
except ValidationError as exc:
    # 422 from the server — print the structured detail.
    for entry in exc.errors:
        print(entry["loc"], entry["msg"])
except OrchestratorError as exc:
    # base — catches everything the SDK raises
    raise
```

That's the full surface. Read [README.md](../README.md) for the API
table, [CHANGELOG.md](../CHANGELOG.md) for what shipped.
