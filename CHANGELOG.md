# Changelog

All notable changes to `ai-orchestrator-client` are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [PEP 440](https://peps.python.org/pep-0440/).

## [0.1.0a1] — 2026-05-08

### Added

- **`CampaignTemplate.hitl_mode`** field mirroring AI Orchestrator
  Phase 3.1 (server tag `v0.3.1-phase3.1`). Optional string; valid
  values are `full_auto` / `gate_only` / `checkpoint` /
  `step_by_step` / `co_pilot`. Older orchestrators ignore the field;
  newer orchestrators fall back to `full_auto` when unset, so the
  bump is fully backwards-compatible.

### Notes

- The Phase 3.1 server-side `POST /runs/{run_id}/intervene` route
  (approve / reject / edit) is reachable today via the underlying
  `httpx.Client`; a typed `intervene_run` method on the SDK ships in
  a follow-up.

## [0.1.0a0] — 2026-05-07

First public alpha. Wraps every SDK-relevant endpoint of AI Orchestrator
0.1.5 (Phase 1.5 — SHA256 manifests + Merkle root + verify CLI, on `main`
at orchestrator commit `14124fb`).

### Added

- **Sync `OrchestratorClient` and async `AsyncOrchestratorClient`** with
  identical method surfaces (only `async def` differs).
  - Run lifecycle: `run`, `get_status`, `wait_for_completion`,
    `get_result`, `verify_run`, `tail_log`.
  - Idempotent control: `pause`, `resume`, `restart`,
    `control_status` — guard the server's toggle endpoint so
    `resume()` never accidentally pauses a running orchestrator.
  - Campaign lifecycle: `start_campaign`, `list_campaigns`,
    `get_campaign`, `get_campaign_tree`,
    `pause_campaign` / `resume_campaign` / `abort_campaign`,
    `verify_campaign_merkle`.
  - Phase 1.2 evidence: `get_evidence`, `download_evidence_crate`,
    `refresh_evidence`.
- **`Campaign.iter_runs(client, ...)`** polling generator (sync +
  async) handling the empty-`runs[]` race after campaign creation.
  Termination requires terminal status AND zero new run ids in the
  most recent poll.
- **`AsyncOrchestratorClient.iter_logs(run_id, ...)`** WebSocket-backed
  async generator yielding typed `LogEvent` and `StatusEvent`.
  Reconnect-once on transient `ConnectionClosed`.
- **`BearerTokenAuth`** — forward-compat token shell. No-op against the
  Phase 1.6 server (no auth); honored by Phase 1.7+ without code
  changes. Auth headers are merged per-request so token-rotating
  providers always send fresh credentials.
- **Pydantic v2 wire mirrors** for every endpoint. Drift-protected
  against a captured `tests/fixtures/openapi-v0.1.json`.
- **Typed errors**: `OrchestratorError` base, `OrchestratorAPIError`
  (with `status_code` + `body`), `NotFound` (404),
  `ValidationError` (422 — surfaces FastAPI structured `detail`
  via `.errors`), `ServiceUnavailable` (503), `RunFailed`,
  `WaitTimeout`, `WaitInterrupted`.
- **PEP 561 `py.typed` marker** so consumers get type info from the
  installed wheel.
- **CI** matrix on Python 3.11 + 3.12 (ruff, mypy `--strict`, pytest).
- **Trusted Publishing** release workflow (`.github/workflows/release.yml`)
  triggered by `v*` tags. See [RELEASING.md](RELEASING.md) for the
  one-time PyPI registration prerequisites; the workflow runs ruff,
  mypy, and pytest as a final gate before upload.

### Limitations / known follow-ups (deferred to 0.1.1+)

- `download_evidence_crate` materializes the whole RO-Crate ZIP in
  memory. A streaming-to-path variant is queued for a follow-up.
- `list_campaigns` returns `list[dict]` rather than a typed
  `CampaignSummary` model — promote when a real consumer needs it.
- `iter_logs` filters client-side (server broadcasts globally on /ws);
  high-volume deployments should prefer `get_status` polling +
  `tail_log` until the server grows per-run subscriptions.
- No `@overload` on `iter_logs(include_status=...)` to narrow the
  return type. Cosmetic — adding in a future minor.

[0.1.0a0]: https://github.com/ernesto01louis/ai-orchestrator-client/releases/tag/v0.1.0a0
