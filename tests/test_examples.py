"""Static checks on examples/ — they parse and import cleanly.

Real execution requires a live orchestrator and is opt-in via the
``live_orchestrator`` marker (not yet wired). These tests prevent the
example scripts from rotting against SDK API changes.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize(
    "filename",
    ["sync_run.py", "async_campaign.py", "stream_logs.py"],
)
def test_example_imports(filename: str) -> None:
    """Import each example as a module — catches API drift cheaply."""
    path = EXAMPLES_DIR / filename
    assert path.exists(), f"example missing: {path}"

    spec = importlib.util.spec_from_file_location(f"_example_{filename[:-3]}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    assert hasattr(module, "main"), f"{filename} missing main()"
