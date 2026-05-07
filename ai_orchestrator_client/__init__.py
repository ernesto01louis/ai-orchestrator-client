"""ai-orchestrator-client — Python SDK for the AI Orchestrator HTTP API."""

from ._auth import AuthProvider, BearerTokenAuth
from ._errors import (
    NotFound,
    OrchestratorAPIError,
    OrchestratorError,
    RunFailed,
    ServiceUnavailable,
    ValidationError,
    WaitInterrupted,
    WaitTimeout,
)
from .async_client import AsyncOrchestratorClient
from .models import (
    Campaign,
    CampaignAck,
    CampaignControlAck,
    CampaignCreate,
    CampaignRun,
    CampaignStatus,
    CampaignTemplate,
    CampaignTreeRun,
    CampaignTreeView,
    CampaignVerifyResult,
    LogEvent,
    ManifestStatus,
    OrchestrateAck,
    OrchestrateRequest,
    OrchestrateResult,
    RunningResult,
    RunPhase,
    RunStatus,
    RunVerifyResult,
    StatusEvent,
)
from .sync_client import OrchestratorClient

__version__ = "0.1.0a0"

__all__ = [
    "__version__",
    # clients
    "AsyncOrchestratorClient",
    "OrchestratorClient",
    # auth
    "AuthProvider",
    "BearerTokenAuth",
    # errors
    "NotFound",
    "OrchestratorAPIError",
    "OrchestratorError",
    "RunFailed",
    "ServiceUnavailable",
    "ValidationError",
    "WaitInterrupted",
    "WaitTimeout",
    # models
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
    "LogEvent",
    "ManifestStatus",
    "OrchestrateAck",
    "OrchestrateRequest",
    "OrchestrateResult",
    "RunPhase",
    "RunStatus",
    "RunVerifyResult",
    "RunningResult",
    "StatusEvent",
]
