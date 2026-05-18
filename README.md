# ai-orchestrator-client

Python SDK for the [AI Orchestrator](https://github.com/ernesto01louis/ai-orchestrator).

This is the **primary consumer contract** for the orchestrator platform.
Research projects (aerodynamics optimization, RF DF, music generation,
anything) install this library, call `OrchestratorClient.run(...)` or
`OrchestratorClient.start_campaign(...)`, and stream results back without
having to know the HTTP surface.

> **Status:** alpha. First PyPI release: `0.1.0a0`. See
> [CHANGELOG.md](CHANGELOG.md) for shipping work.

## Install

```bash
pip install ai-orchestrator-client
```

Python 3.11+. Wraps the orchestrator's HTTP API + `/ws` log stream;
async-first under the hood with a sync façade for scripts.

## Quick start

### Submit a single run (sync)

```python
from ai_orchestrator_client import OrchestrateRequest, OrchestratorClient

req = OrchestrateRequest(
    project_name="hello-world",
    prompt="Write a Python script that prints fizzbuzz to 30.",
    planner_model="qwen2.5-coder:14b",
    generator_models=["qwen2.5-coder:14b"],
    judge_model="qwen2.5-coder:14b",
    deploy_target="local",
)

with OrchestratorClient(base_url="http://localhost:8000") as client:
    ack = client.run(req)
    final = client.wait_for_completion(ack.run_id, timeout=600)
    print(final.score, final.result)
```

### Submit a campaign (parameter sweep) and stream results (async)

```python
import asyncio
from ai_orchestrator_client import (
    AsyncOrchestratorClient, CampaignCreate, CampaignTemplate,
)

async def main() -> None:
    req = CampaignCreate(
        name="seed-sweep",
        hypothesis="output is invariant across seeds 1..4",
        template=CampaignTemplate(
            project_name="hello-{seed}",
            prompt="Print fizzbuzz with seed {seed}.",
            planner_model="qwen2.5-coder:14b",
            generator_models=["qwen2.5-coder:14b"],
            judge_model="qwen2.5-coder:14b",
            deploy_target="local",
        ),
        params={"seed": [1, 2, 3, 4]},
    )

    async with AsyncOrchestratorClient(base_url="http://localhost:8000") as client:
        ack = await client.start_campaign(req)
        campaign = await client.get_campaign(ack.campaign_id)
        async for run in campaign.iter_runs(client):
            print("new run:", run.run_id, run.params)
        verify = await client.verify_campaign_merkle(ack.campaign_id)
        print("merkle ok?", verify.valid)

asyncio.run(main())
```

### Stream live log lines via WebSocket

```python
import asyncio
from ai_orchestrator_client import AsyncOrchestratorClient

async def tail() -> None:
    async with AsyncOrchestratorClient(base_url="http://localhost:8000") as client:
        async for event in client.iter_logs("run-uuid-here", include_status=True):
            # LogEvent or StatusEvent — terminates on completed=True
            print(event)

asyncio.run(tail())
```

### Forward-compatible auth

The orchestrator's HTTP surface has no auth in 1.6 — Phase 1.7 adds bearer
tokens. Wire your token now and it'll start being honored once the server
ships:

```python
from ai_orchestrator_client import BearerTokenAuth, OrchestratorClient
client = OrchestratorClient(base_url=..., auth=BearerTokenAuth(token))
```

## What's here

| Surface | Sync | Async |
| --- | --- | --- |
| Run lifecycle (`run`, `get_status`, `wait_for_completion`, `get_result`, `verify_run`, `tail_log`) | ✓ | ✓ |
| Control (`pause`, `resume`, `restart`, idempotent against the server's toggle endpoint) | ✓ | ✓ |
| Campaigns (`start_campaign`, `get_campaign`, `get_campaign_tree`, `pause`/`resume`/`abort`, `verify_campaign_merkle`) | ✓ | ✓ |
| Evidence (`get_evidence`, `download_evidence_crate`, `refresh_evidence`) | ✓ | ✓ |
| `Campaign.iter_runs(client)` streaming with empty-`runs[]` race guard | ✓ | ✓ |
| Live log streaming via `/ws` (`iter_logs`) | — | ✓ |
| Consumer registry (`register_consumer`, `list_consumers`, `get_consumer`, `deregister_consumer`, `consumer_heartbeat`) | ✓ | ✓ |
| Capability dispatch (`invoke_capability`) | ✓ | ✓ |
| Consumer data-plane push (`write_memory`, `write_vault_note`, `send_notification`, `push_evidence`) | ✓ | ✓ |
| `Consumer` base + `@capability` + `dispatch()` (framework-free) | ✓ | ✓ |
| `Hindsight` / `Vault` / `Ntfy` thin push clients | ✓ | — |
| Bearer-token auth hooks (no-op until orchestrator Phase 1.7 ships token auth) | ✓ | ✓ |
| Typed Pydantic models for every endpoint | ✓ | ✓ |
| OpenAPI drift fixture protecting wire-format mirrors | n/a | n/a |

### Registering as a consumer (Phase 3.6)

An external project registers with the orchestrator, declares
capabilities, and exposes handlers the orchestrator can dispatch work to:

```python
from ai_orchestrator_client import Consumer, capability, OrchestratorClient

class RfdfConsumer(Consumer):
    name = "rfdf"

    @capability("rf.doa.run")
    async def run_doa(self, payload: dict) -> dict:
        ...  # delegate to your platform

with OrchestratorClient(base_url="http://orchestrator.lan:8000") as client:
    consumer = RfdfConsumer()
    consumer.register(client, base_url="http://rfdf.lan:8000",
                      callback_token="…",
                      extra_capabilities=["memory.write"])

# In your own POST /capabilities/{cap} handler:
result = await consumer.dispatch(cap, payload)
```

`Consumer` imports no web framework — wire `dispatch()` into whatever
HTTP server the consumer project already runs.

## Errors

Catch `OrchestratorError` for the whole family. Specific subclasses for
common failure modes:

- `NotFound` — server returned 404 (unknown run/campaign id)
- `ValidationError` — server returned 422; structured FastAPI detail
  preserved on `.errors`
- `ServiceUnavailable` — server returned 503 (typically: orchestrator
  paused via `/control/pause`)
- `RunFailed` — `wait_for_completion` saw `completed=True` with a
  non-empty `error` field
- `WaitTimeout` — `wait_for_completion` exceeded its `timeout`
- `WaitInterrupted` — caller-supplied `stop_event` fired during a poll

## Notes

- `download_evidence_crate(campaign_id)` materializes the whole RO-Crate
  ZIP in memory — fine for typical bundles, but for multi-GB crates a
  streaming-to-path variant will land in a follow-up.
- `iter_logs` filters frames client-side because the orchestrator's
  `/ws` broadcasts globally; high-traffic deployments should prefer
  `get_status()` polling + `tail_log()`.

## Examples

Runnable scripts in [examples/](examples/):
- `examples/sync_run.py` — single run end-to-end with the sync client
- `examples/async_campaign.py` — campaign + streaming runs + Merkle verify
- `examples/stream_logs.py` — live log tail via WS

Each script reads `ORCHESTRATOR_URL` (default
`http://localhost:8000`) and an optional `ORCHESTRATOR_TOKEN`.

## License

Apache 2.0 — see [LICENSE](LICENSE).
