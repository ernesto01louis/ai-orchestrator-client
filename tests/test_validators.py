"""Tests for client-side input validation.

Mirrors the server-side SAFE_FILENAME regex in ai-orchestrator
(app.py / api/routes.py). If these tests fail and the server hasn't
changed, the SDK has drifted; if the server changed, update both in
lockstep.
"""
from __future__ import annotations

import pytest

from ai_orchestrator_client import (
    OrchestrateRequest,
    OrchestratorError,
    ProjectNameInvalidError,
)
from ai_orchestrator_client._validators import (
    SAFE_FILENAME_PATTERN,
    validate_project_name,
)

VALID_NAMES = [
    "naca0012-baseline",
    "riblet_sweep_v3",
    "run.42",
    "a",
    "A",
    "0",
    "_",
    "-",
    ".",
    "Project.Name_v2-final",
    "a.b.c.d.e",
]


INVALID_NAMES = [
    "",                       # empty
    "My Project!",            # space + punctuation
    "foo/bar",                # slash (path separator)
    "../etc/passwd",          # explicit traversal
    "..",                     # the traversal token itself
    "foo..bar",               # traversal anywhere in the string
    "name with spaces",       # spaces
    "name@host",              # @
    "ñame",                   # non-ascii
    "name?",                  # ?
    "name#tag",               # #
    "name$",                  # $
]


@pytest.mark.parametrize("name", VALID_NAMES)
def test_valid_names_pass(name: str) -> None:
    assert validate_project_name(name) == name
    assert SAFE_FILENAME_PATTERN.match(name) is not None


@pytest.mark.parametrize("name", INVALID_NAMES)
def test_invalid_names_raise(name: str) -> None:
    with pytest.raises(ProjectNameInvalidError) as exc_info:
        validate_project_name(name)
    # error mentions the offending value (or its repr for non-strings)
    assert name in str(exc_info.value) or repr(name) in str(exc_info.value)
    # subclass relationship — callers can catch OrchestratorError
    assert isinstance(exc_info.value, OrchestratorError)


def test_non_string_raises() -> None:
    with pytest.raises(ProjectNameInvalidError):
        validate_project_name(None)  # type: ignore[arg-type]
    with pytest.raises(ProjectNameInvalidError):
        validate_project_name(42)  # type: ignore[arg-type]


def _minimal_orchestrate_kwargs(project_name: str) -> dict:
    return dict(
        project_name=project_name,
        prompt="hello",
        planner_model="x",
        generator_models=["x"],
        judge_model="x",
        deploy_target="local",
    )


def test_orchestrate_request_validates_project_name() -> None:
    # Valid: model constructs cleanly.
    req = OrchestrateRequest(**_minimal_orchestrate_kwargs("naca0012-baseline"))
    assert req.project_name == "naca0012-baseline"

    # Invalid: pydantic v2 only wraps ValueError / AssertionError into
    # PydanticValidationError; our ProjectNameInvalidError propagates
    # directly, which is what we want — consumers get a typed exception
    # instead of having to dig through ValidationError.errors().
    with pytest.raises(ProjectNameInvalidError) as exc_info:
        OrchestrateRequest(**_minimal_orchestrate_kwargs("bad name!"))
    assert "bad name!" in str(exc_info.value)


def test_error_message_contains_helpful_examples() -> None:
    with pytest.raises(ProjectNameInvalidError) as exc_info:
        validate_project_name("bad name!")
    msg = str(exc_info.value)
    # Examples and rule both present
    assert "naca0012-baseline" in msg
    assert "Allowed" in msg
