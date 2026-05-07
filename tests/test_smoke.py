"""Smoke tests for the package skeleton."""
from __future__ import annotations

from packaging.version import InvalidVersion, Version

import ai_orchestrator_client
from ai_orchestrator_client._base import USER_AGENT


def test_version_is_pep440_string() -> None:
    version = ai_orchestrator_client.__version__
    assert isinstance(version, str)
    try:
        Version(version)
    except InvalidVersion as exc:  # pragma: no cover — assertion message
        raise AssertionError(f"__version__ {version!r} is not PEP 440") from exc


def test_version_exposed_on_package() -> None:
    assert "__version__" in ai_orchestrator_client.__all__


def test_user_agent_tracks_package_version() -> None:
    """Regression guard: a version bump must reach USER_AGENT.

    USER_AGENT is built lazily via importlib.metadata; if the editable
    install becomes stale or the bump is forgotten in pyproject.toml,
    this fails loudly instead of silently shipping the old version on
    the wire.
    """
    assert USER_AGENT.endswith(f"/{ai_orchestrator_client.__version__}"), (
        f"USER_AGENT={USER_AGENT!r} does not end with /{ai_orchestrator_client.__version__}"
    )
