"""Tests for the Phase 3.6 consumer surface.

Covers the consumer models (round-trip), the framework-agnostic
``Consumer`` base + ``@capability`` decorator + ``dispatch``, the
``Hindsight`` / ``Vault`` / ``Ntfy`` thin clients, and the sync + async
client methods (respx-mocked HTTP).
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx

from ai_orchestrator_client import (
    AsyncOrchestratorClient,
    CapabilityInvokeResult,
    Consumer,
    ConsumerAck,
    ConsumerRecord,
    ConsumerRegistration,
    EvidencePush,
    Hindsight,
    Notification,
    Ntfy,
    OrchestratorClient,
    UnknownCapabilityError,
    Vault,
    VaultNote,
    capability,
)

BASE = "http://orchestrator.test"


@pytest.fixture
def client() -> Iterator[OrchestratorClient]:
    with OrchestratorClient(base_url=BASE) as c:
        yield c


@pytest.fixture
async def aclient() -> AsyncIterator[AsyncOrchestratorClient]:
    async with AsyncOrchestratorClient(base_url=BASE) as c:
        yield c


# ── models ───────────────────────────────────────────────────────────


def test_consumer_registration_round_trip() -> None:
    reg = ConsumerRegistration(
        consumer_id="rfdf",
        name="rf-direction-finding",
        base_url="http://rfdf.lan:8000",
        capabilities=["rf.doa.run", "memory.write"],
        callback_token="tok",
    )
    assert ConsumerRegistration.model_validate(reg.model_dump()) == reg


def test_consumer_record_ignores_unknown_fields() -> None:
    rec = ConsumerRecord.model_validate(
        {
            "consumer_id": "rfdf",
            "name": "rf",
            "base_url": "http://x",
            "capabilities": ["rf.doa.run"],
            "has_callback_token": True,
            "a_field_a_newer_server_added": 123,
        }
    )
    assert rec.consumer_id == "rfdf"
    assert rec.has_callback_token is True


# ── Consumer base + @capability + dispatch ────────────────────────────


class _RfdfConsumer(Consumer):
    name = "rfdf"

    @capability("rf.doa.run")
    async def run_doa(self, payload: dict) -> dict:
        return {"bearing_deg": payload.get("freq_hz", 0) / 1e7}

    @capability("rf.classify")
    def classify(self, payload: dict) -> dict:
        return {"modulation": "OFDM"}


def test_capability_registry_built_per_subclass() -> None:
    assert _RfdfConsumer().capabilities == ["rf.classify", "rf.doa.run"]


def test_dispatch_routes_async_and_sync_handlers() -> None:
    c = _RfdfConsumer()
    assert asyncio.run(c.dispatch("rf.doa.run", {"freq_hz": 8.7e8})) == {
        "bearing_deg": 87.0
    }
    assert asyncio.run(c.dispatch("rf.classify", {})) == {"modulation": "OFDM"}


def test_dispatch_unknown_capability_raises() -> None:
    with pytest.raises(UnknownCapabilityError):
        asyncio.run(_RfdfConsumer().dispatch("rf.ghost", {}))


def test_to_registration_merges_extra_capabilities() -> None:
    reg = _RfdfConsumer().to_registration(
        "http://rfdf.lan:8000",
        callback_token="t",
        extra_capabilities=["memory.write", "vault.write"],
    )
    assert reg.consumer_id == "rfdf"
    assert reg.capabilities == [
        "memory.write",
        "rf.classify",
        "rf.doa.run",
        "vault.write",
    ]


def test_health_report() -> None:
    report = _RfdfConsumer().health()
    assert report.name == "rfdf"
    assert report.status == "ok"
    assert "rf.doa.run" in report.capabilities


# ── sync client methods ──────────────────────────────────────────────


@respx.mock
def test_register_consumer(client: OrchestratorClient) -> None:
    respx.post(f"{BASE}/consumers/register").mock(
        return_value=httpx.Response(
            201,
            json={
                "status": "registered",
                "consumer": {
                    "consumer_id": "rfdf",
                    "name": "rf",
                    "base_url": "http://rfdf.lan:8000",
                    "capabilities": ["rf.doa.run"],
                    "has_callback_token": True,
                },
            },
        )
    )
    ack = client.register_consumer(
        ConsumerRegistration(
            consumer_id="rfdf", name="rf", base_url="http://rfdf.lan:8000"
        )
    )
    assert isinstance(ack, ConsumerAck)
    assert ack.status == "registered"
    assert ack.consumer.consumer_id == "rfdf"


@respx.mock
def test_list_consumers(client: OrchestratorClient) -> None:
    respx.get(f"{BASE}/consumers").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 1,
                "consumers": [
                    {
                        "consumer_id": "rfdf",
                        "name": "rf",
                        "base_url": "http://x",
                        "capabilities": [],
                    }
                ],
            },
        )
    )
    consumers = client.list_consumers()
    assert len(consumers) == 1
    assert consumers[0].consumer_id == "rfdf"


@respx.mock
def test_invoke_capability(client: OrchestratorClient) -> None:
    route = respx.post(f"{BASE}/capabilities/rf.doa.run/invoke").mock(
        return_value=httpx.Response(
            200,
            json={
                "capability": "rf.doa.run",
                "consumer_id": "rfdf",
                "result": {"bearing_deg": 47.0},
            },
        )
    )
    out = client.invoke_capability("rf.doa.run", {"freq_hz": 8.68e8})
    assert isinstance(out, CapabilityInvokeResult)
    assert out.result == {"bearing_deg": 47.0}
    import json as _json

    assert _json.loads(route.calls.last.request.content) == {
        "payload": {"freq_hz": 8.68e8}
    }


@respx.mock
def test_push_endpoints(client: OrchestratorClient) -> None:
    respx.post(f"{BASE}/consumers/rfdf/memory").mock(
        return_value=httpx.Response(200, json={"status": "success", "retained": True})
    )
    respx.post(f"{BASE}/consumers/rfdf/vault").mock(
        return_value=httpx.Response(200, json={"status": "success", "path": "/v/x.md"})
    )
    respx.post(f"{BASE}/consumers/rfdf/notify").mock(
        return_value=httpx.Response(200, json={"status": "sent"})
    )
    respx.post(f"{BASE}/consumers/rfdf/evidence").mock(
        return_value=httpx.Response(200, json={"status": "stored", "bundle_id": "b1"})
    )
    assert client.write_memory("rfdf", "detected emitter")["retained"] is True
    assert client.write_vault_note(
        "rfdf", VaultNote(title="calib", body="matrix")
    )["status"] == "success"
    assert client.send_notification(
        "rfdf", Notification(title="drift", message="cal drift")
    )["status"] == "sent"
    assert client.push_evidence(
        "rfdf", EvidencePush(bundle={"quality": "citation-grade"})
    )["bundle_id"] == "b1"


# ── thin clients ─────────────────────────────────────────────────────


@respx.mock
def test_thin_clients(client: OrchestratorClient) -> None:
    mem = respx.post(f"{BASE}/consumers/rfdf/memory").mock(
        return_value=httpx.Response(200, json={"status": "success", "retained": True})
    )
    vault = respx.post(f"{BASE}/consumers/rfdf/vault").mock(
        return_value=httpx.Response(200, json={"status": "success", "path": "/v.md"})
    )
    ntfy = respx.post(f"{BASE}/consumers/rfdf/notify").mock(
        return_value=httpx.Response(200, json={"status": "sent"})
    )
    Hindsight(client, "rfdf").write("emitter at 47deg")
    Vault(client, "rfdf").write_note("geometry", "ULA preset", tags=["rf"])
    Ntfy(client, "rfdf").alert("anomaly", "high-SNR drone", priority=4)
    assert mem.called and vault.called and ntfy.called


# ── async parity ─────────────────────────────────────────────────────


@respx.mock
async def test_async_register_and_invoke(aclient: AsyncOrchestratorClient) -> None:
    respx.post(f"{BASE}/consumers/register").mock(
        return_value=httpx.Response(
            201,
            json={
                "status": "registered",
                "consumer": {
                    "consumer_id": "rfdf",
                    "name": "rf",
                    "base_url": "http://x",
                    "capabilities": [],
                },
            },
        )
    )
    respx.post(f"{BASE}/capabilities/rf.doa.run/invoke").mock(
        return_value=httpx.Response(
            200,
            json={"capability": "rf.doa.run", "consumer_id": "rfdf", "result": 1},
        )
    )
    ack = await aclient.register_consumer(
        ConsumerRegistration(consumer_id="rfdf", name="rf", base_url="http://x")
    )
    assert ack.status == "registered"
    out = await aclient.invoke_capability("rf.doa.run", {})
    assert out.result == 1
