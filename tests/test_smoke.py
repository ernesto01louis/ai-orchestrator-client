"""Smoke tests for the package skeleton."""
from __future__ import annotations

from packaging.version import InvalidVersion, Version

import ai_orchestrator_client


def test_version_is_pep440_string() -> None:
    version = ai_orchestrator_client.__version__
    assert isinstance(version, str)
    try:
        Version(version)
    except InvalidVersion as exc:  # pragma: no cover — assertion message
        raise AssertionError(f"__version__ {version!r} is not PEP 440") from exc


def test_version_exposed_on_package() -> None:
    assert "__version__" in ai_orchestrator_client.__all__
