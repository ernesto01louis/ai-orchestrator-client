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
    ManifestStatus,
    OrchestrateAck,
    OrchestrateRequest,
    OrchestrateResult,
    RunningResult,
    RunPhase,
    RunStatus,
    RunVerifyResult,
)
from .sync_client import OrchestratorClient

__version__ = "0.0.0"

__all__ = [
    "__version__",
    # client
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
    "ManifestStatus",
    "OrchestrateAck",
    "OrchestrateRequest",
    "OrchestrateResult",
    "RunPhase",
    "RunStatus",
    "RunVerifyResult",
    "RunningResult",
]
