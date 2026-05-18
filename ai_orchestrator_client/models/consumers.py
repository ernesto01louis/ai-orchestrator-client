"""Phase 3.6 consumer-registry models.

Mirrors the orchestrator's ``api/routes/consumers.py`` request bodies
and response envelopes: the consumer registry, capability dispatch, and
the data-plane push endpoints (memory / vault / notify / evidence).

Request models are validated client-side; response models use
``ConfigDict(extra="ignore")`` so a newer server adding fields never
breaks an older SDK.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConsumerRegistration(BaseModel):
    """``POST /consumers/register`` body.

    ``callback_token`` is the outbound credential the orchestrator
    presents when dispatching a capability call back to this consumer —
    omit it for a push-only consumer that never receives dispatched
    work. ``capabilities`` lists both domain capabilities (``rf.doa.run``)
    and the generic data-plane grants (``memory.write`` / ``vault.write``
    / ``notify.send`` / ``evidence.push``).
    """

    consumer_id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1)
    base_url: str = Field(..., min_length=1)
    capabilities: list[str] = Field(default_factory=list)
    callback_token: str | None = None
    description: str = ""


class ConsumerRecord(BaseModel):
    """A registered consumer as returned by ``GET /consumers`` /
    ``GET /consumers/{id}``. The ``callback_token`` is never returned —
    ``has_callback_token`` is a presence flag instead."""

    model_config = ConfigDict(extra="ignore")

    consumer_id: str
    name: str
    base_url: str
    capabilities: list[str] = Field(default_factory=list)
    description: str = ""
    registered_at: str | None = None
    updated_at: str | None = None
    last_heartbeat: str | None = None
    last_health: dict[str, Any] | None = None
    has_callback_token: bool = False


class ConsumerAck(BaseModel):
    """``POST /consumers/register`` response."""

    model_config = ConfigDict(extra="ignore")

    status: str
    consumer: ConsumerRecord


class CapabilityInvokeResult(BaseModel):
    """``POST /capabilities/{capability}/invoke`` response — the
    consumer's own result is carried verbatim on ``result``."""

    model_config = ConfigDict(extra="ignore")

    capability: str
    consumer_id: str
    result: Any = None


class MemoryWrite(BaseModel):
    """``POST /consumers/{id}/memory`` body — a natural-language
    narrative Hindsight extracts facts from."""

    content: str = Field(..., min_length=1)


class VaultNote(BaseModel):
    """``POST /consumers/{id}/vault`` body — an L5 vault note."""

    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)


class Notification(BaseModel):
    """``POST /consumers/{id}/notify`` body — an ntfy/Gotify alert."""

    title: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    priority: int | None = None
    tags: list[str] = Field(default_factory=list)


class EvidencePush(BaseModel):
    """``POST /consumers/{id}/evidence`` body.

    The ``bundle`` stays in the consumer's own schema — the orchestrator
    persists it verbatim and does not parse it. ``bundle_id`` is
    optional; the server generates one when omitted.
    """

    bundle: dict[str, Any] = Field(default_factory=dict)
    bundle_id: str | None = None


class HealthReport(BaseModel):
    """A consumer's self-reported health, surfaced by ``Consumer.health()``."""

    name: str
    status: str = "ok"
    capabilities: list[str] = Field(default_factory=list)
