# ai-orchestrator-client

Python SDK for the [AI Orchestrator](https://github.com/ernesto01louis/ai-orchestrator).

This is the **primary consumer contract** for the orchestrator platform.
Research projects (aerodynamics, RF, music generation, anything) install
this library, call `OrchestratorClient.run(...)` or
`OrchestratorClient.start_campaign(...)`, and stream results back without
having to know the HTTP surface.

> Status: **alpha** — under active development. No PyPI release yet.
> First release will be `0.1.0a0`. See [CHANGELOG.md](CHANGELOG.md).

## Install (once published)

```bash
pip install ai-orchestrator-client
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
