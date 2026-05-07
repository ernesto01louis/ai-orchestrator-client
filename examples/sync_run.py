"""Submit a single orchestration run and wait for completion (sync).

Reads `ORCHESTRATOR_URL` (default http://127.0.0.1:8000) and optional
`ORCHESTRATOR_TOKEN` env vars. Run with::

    python examples/sync_run.py
"""
from __future__ import annotations

import os
import sys

from ai_orchestrator_client import (
    BearerTokenAuth,
    OrchestrateRequest,
    OrchestratorClient,
    RunFailed,
    WaitTimeout,
)


def main() -> int:
    base_url = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8000")
    token = os.environ.get("ORCHESTRATOR_TOKEN")
    auth = BearerTokenAuth(token) if token else None

    req = OrchestrateRequest(
        project_name="sdk-demo",
        prompt="Write a Python one-liner that prints 'hello from sdk'.",
        planner_model="qwen2.5-coder:14b",
        generator_models=["qwen2.5-coder:14b"],
        judge_model="qwen2.5-coder:14b",
        deploy_target="local",
        max_iterations=2,
    )

    with OrchestratorClient(base_url=base_url, auth=auth) as client:
        print(f"-> POST /orchestrate  (server: {base_url})")
        ack = client.run(req)
        print(f"   run_id={ack.run_id}  flow_run_id={ack.flow_run_id}")

        try:
            final = client.wait_for_completion(ack.run_id, timeout=600.0)
        except WaitTimeout as exc:
            print(f"!! timed out: {exc}")
            return 2
        except RunFailed as exc:
            print(f"!! run failed: {exc.error}")
            return 1

        print(f"   completed  phase={final.phase}  score={final.score}")
        print(f"   manifest_status={final.manifest_status}")

        verify = client.verify_run(ack.run_id)
        print(f"-> verify_run: valid={verify.valid}  status={verify.status}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
