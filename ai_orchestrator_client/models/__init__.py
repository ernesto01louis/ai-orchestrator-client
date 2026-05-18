"""Wire-compatible Pydantic mirrors of the orchestrator's HTTP contract.

Mirrors are hand-written rather than generated from /openapi.json — server
schemas use ad-hoc dicts for response envelopes that openapi-codegen would
miss. A drift check (tests/test_openapi_drift.py) protects the request/CRUD
schemas (OrchestrateRequest, CampaignCreate, CampaignTemplate) by comparing
against a captured fixture; response envelopes are validated by round-trip
tests instead.
"""

from .campaign import (
    Campaign,
    CampaignAck,
    CampaignControlAck,
    CampaignCreate,
    CampaignRun,
    CampaignTemplate,
    CampaignTreeRun,
    CampaignTreeView,
)
from .consumers import (
    CapabilityInvokeResult,
    ConsumerAck,
    ConsumerRecord,
    ConsumerRegistration,
    EvidencePush,
    HealthReport,
    MemoryWrite,
    Notification,
    VaultNote,
)
from .events import LogEvent, StatusEvent
from .orchestrate import (
    OrchestrateAck,
    OrchestrateRequest,
    OrchestrateResult,
    RunningResult,
    RunStatus,
)
from .status import CampaignStatus, ManifestStatus, RunPhase
from .verify import CampaignVerifyResult, RunVerifyResult

__all__ = [
    "Campaign",
    "CampaignAck",
    "CampaignControlAck",
    "CampaignCreate",
    "CampaignRun",
    "CampaignStatus",
    "CampaignTemplate",
    "CampaignTreeRun",
    "CampaignTreeView",
    "CampaignVerifyResult",
    "CapabilityInvokeResult",
    "ConsumerAck",
    "ConsumerRecord",
    "ConsumerRegistration",
    "EvidencePush",
    "HealthReport",
    "LogEvent",
    "ManifestStatus",
    "MemoryWrite",
    "Notification",
    "OrchestrateAck",
    "OrchestrateRequest",
    "OrchestrateResult",
    "RunPhase",
    "RunStatus",
    "RunVerifyResult",
    "RunningResult",
    "StatusEvent",
    "VaultNote",
]
