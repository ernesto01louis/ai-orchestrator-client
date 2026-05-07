"""Shared status / phase Literals used across run, campaign, and verify models."""
from __future__ import annotations

from typing import Literal

# Mirrors manifest.run_manifest.ManifestStatus (server-side).
# "ok": every artifact's stored sha256 matches disk.
# "corrupted": at least one artifact mismatches.
# "missing": manifest.json absent (run skipped or failed before write).
# "skipped": orchestration hook intentionally bypassed manifest writing.
ManifestStatus = Literal["ok", "corrupted", "missing", "skipped"]

# Mirrors core.campaign.CampaignStatus (server-side).
CampaignStatus = Literal[
    "queued", "running", "paused", "completed", "aborted", "failed"
]

# Free-form on the server (set ad-hoc by orchestration hooks); these are the
# observed terminal/non-terminal phase strings. Treat as advisory: the only
# authoritative completion signal is RunStatus.completed (Prefect retries can
# flap a "executing" -> "executing" transition that string-equality misses).
RunPhase = Literal[
    "queued",
    "planning",
    "executing",
    "judging",
    "optimizing",
    "troubleshooting",
    "completed",
    "failed",
]
