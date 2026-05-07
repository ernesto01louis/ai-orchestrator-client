"""Verify (manifest integrity) result models.

Mirrors api/routes.py:398 (GET /runs/{id}/verify) and
api/routes.py:2349 (GET /campaigns/{id}/verify-merkle). Both endpoints
share `valid` / `status` / `mismatches` plus an id field.
"""
from __future__ import annotations

from pydantic import BaseModel

from .status import ManifestStatus


class RunVerifyResult(BaseModel):
    """GET /runs/{run_id}/verify response."""

    run_id: str
    valid: bool
    status: ManifestStatus
    mismatches: list[str]


class CampaignVerifyResult(BaseModel):
    """GET /campaigns/{campaign_id}/verify-merkle response."""

    campaign_id: str
    valid: bool
    status: ManifestStatus
    mismatches: list[str]
