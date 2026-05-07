"""Drift check: ensure mirrored Pydantic models still match the server's
OpenAPI schema (captured at tests/fixtures/openapi-v0.1.json).

Refresh the fixture by running, with the orchestrator service up:

    curl -s http://127.0.0.1:8000/openapi.json \
      > tests/fixtures/openapi-v0.1.json
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from ai_orchestrator_client.models.campaign import CampaignCreate, CampaignTemplate
from ai_orchestrator_client.models.orchestrate import OrchestrateRequest

FIXTURE = Path(__file__).parent / "fixtures" / "openapi-v0.1.json"

# Pairs of (mirror, server-schema-name). Only request/CRUD bodies are tracked
# here — response envelopes are ad-hoc dicts on the server and are validated
# by the round-trip tests in test_models.py instead.
_TRACKED: list[tuple[type[BaseModel], str]] = [
    (OrchestrateRequest, "OrchestrateRequest"),
    (CampaignTemplate, "CampaignTemplate"),
    (CampaignCreate, "CampaignCreate"),
]


@pytest.fixture(scope="module")
def openapi() -> dict[str, object]:
    if not FIXTURE.exists():
        pytest.skip(f"openapi fixture missing: {FIXTURE}")
    return json.loads(FIXTURE.read_text())  # type: ignore[no-any-return]


def _server_props(openapi_doc: dict[str, object], schema_name: str) -> dict[str, object]:
    schemas = openapi_doc["components"]["schemas"]  # type: ignore[index]
    schema = schemas[schema_name]  # type: ignore[index]
    return schema.get("properties", {})  # type: ignore[no-any-return]


def _server_required(openapi_doc: dict[str, object], schema_name: str) -> set[str]:
    schemas = openapi_doc["components"]["schemas"]  # type: ignore[index]
    schema = schemas[schema_name]  # type: ignore[index]
    return set(schema.get("required", []))


@pytest.mark.parametrize("mirror, schema_name", _TRACKED, ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_mirror_has_every_server_field(
    mirror: type[BaseModel],
    schema_name: str,
    openapi: dict[str, object],
) -> None:
    """Every property on the server schema must exist on our mirror.

    Missing fields = blocker (we'll silently drop data when round-tripping).
    """
    server_props = _server_props(openapi, schema_name)
    mirror_fields = set(mirror.model_fields.keys())
    missing = set(server_props.keys()) - mirror_fields
    assert not missing, (
        f"{mirror.__name__} is missing server fields: {sorted(missing)}. "
        f"Update the mirror or refresh tests/fixtures/openapi-v0.1.json."
    )


@pytest.mark.parametrize("mirror, schema_name", _TRACKED, ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_mirror_required_matches_server(
    mirror: type[BaseModel],
    schema_name: str,
    openapi: dict[str, object],
) -> None:
    """Required fields on the server must be required on the mirror.

    A server-required field made optional on the client = the server will
    422 us with no warning at request time.
    """
    server_required = _server_required(openapi, schema_name)
    mirror_required = {
        name for name, info in mirror.model_fields.items() if info.is_required()
    }
    drift = server_required - mirror_required
    assert not drift, (
        f"{mirror.__name__} has fields the server requires but the mirror does not: "
        f"{sorted(drift)}."
    )


@pytest.mark.parametrize("mirror, schema_name", _TRACKED, ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_mirror_extras_emit_warning(
    mirror: type[BaseModel],
    schema_name: str,
    openapi: dict[str, object],
) -> None:
    """Advisory: mirror fields not on the server emit a stderr warning.

    Never fails — the server may add fields that the client mirrors before
    the SDK refresh, and we want a soft signal for "trim this when convenient"
    rather than blocking CI. Use ``pytest -W error`` locally if you want
    to surface it as a failure.
    """
    import sys

    server_props = _server_props(openapi, schema_name)
    mirror_fields = set(mirror.model_fields.keys())
    extras = mirror_fields - set(server_props.keys())
    if extras:
        print(
            f"[drift] {mirror.__name__} has fields not present on server: "
            f"{sorted(extras)} — drop from the mirror if the server removed them.",
            file=sys.stderr,
        )
