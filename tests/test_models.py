"""Round-trip + validator tests for the mirrored Pydantic models."""
from __future__ import annotations

import pytest

from ai_orchestrator_client import (
    Campaign,
    CampaignAck,
    CampaignControlAck,
    CampaignCreate,
    CampaignRun,
    CampaignTemplate,
    CampaignTreeRun,
    CampaignTreeView,
    CampaignVerifyResult,
    OrchestrateAck,
    OrchestrateRequest,
    OrchestrateResult,
    RunningResult,
    RunStatus,
    RunVerifyResult,
)


def _orchestrate_request_payload() -> dict[str, object]:
    return {
        "project_name": "demo",
        "prompt": "write a hello world script",
        "planner_model": "qwen2.5-coder:14b",
        "generator_models": ["qwen2.5-coder:14b"],
        "judge_model": "qwen2.5-coder:14b",
        "deploy_target": "local",
    }


def _campaign_template_payload() -> dict[str, object]:
    return {
        "project_name": "demo-{seed}",
        "prompt": "write a hello world script using {language}",
        "planner_model": "qwen2.5-coder:14b",
        "generator_models": ["qwen2.5-coder:14b"],
        "judge_model": "qwen2.5-coder:14b",
        "deploy_target": "local",
    }


def _campaign_create_payload() -> dict[str, object]:
    return {
        "name": "language-sweep",
        "description": "Sweep across two seeds and two languages.",
        "hypothesis": "Hello-world output is invariant across seeds and languages.",
        "template": _campaign_template_payload(),
        "params": {"seed": [1, 2], "language": ["python", "bash"]},
        "max_runs": 4,
        "parallelism": 2,
    }


# ---------- OrchestrateRequest ----------


def test_orchestrate_request_required_fields() -> None:
    req = OrchestrateRequest(**_orchestrate_request_payload())
    assert req.project_name == "demo"
    assert req.inspector_model is None
    assert req.optimizer_model is None
    assert req.troubleshooter_model is None
    assert req.max_iterations is None
    assert req.reference_files is None


def test_orchestrate_request_round_trip() -> None:
    req = OrchestrateRequest(**_orchestrate_request_payload())
    assert OrchestrateRequest.model_validate(req.model_dump()) == req


# ---------- OrchestrateAck / RunStatus / RunningResult / OrchestrateResult ----------


def test_orchestrate_ack_minimal() -> None:
    ack = OrchestrateAck(run_id="r-1", status="started", poll="/status/r-1")
    assert ack.flow_run_id is None


def test_run_status_running_run() -> None:
    rs = RunStatus(run_id="r-1", phase="executing", score=None, completed=False)
    assert rs.error is None
    assert rs.result is None
    assert rs.manifest_status is None


def test_run_status_completed_with_manifest() -> None:
    rs = RunStatus(
        run_id="r-1",
        phase="completed",
        score=0.92,
        completed=True,
        manifest_status="ok",
        result={"score": 0.92, "code": "print('hi')"},
    )
    assert rs.manifest_status == "ok"
    assert rs.result == {"score": 0.92, "code": "print('hi')"}


def test_run_status_ignores_unknown_fields() -> None:
    """Server may add fields over time; client must not reject them."""
    rs = RunStatus(
        run_id="r-1",
        phase="executing",
        score=None,
        completed=False,
        future_field_we_dont_know_about=42,  # type: ignore[call-arg]
    )
    assert rs.run_id == "r-1"


def test_running_result_shape() -> None:
    rr = RunningResult(run_id="r-1", status="running", phase="executing")
    assert rr.score is None


def test_orchestrate_result_payload_is_freeform() -> None:
    res = OrchestrateResult(
        run_id="r-1",
        completed=True,
        phase="completed",
        score=0.5,
        manifest_status="ok",
        payload={"any": ["shape", {"the": "generator", "wants": True}]},
    )
    assert res.payload is not None
    assert res.payload["any"][1]["the"] == "generator"


# ---------- CampaignCreate hypothesis validator ----------


def test_campaign_create_round_trip() -> None:
    cc = CampaignCreate(**_campaign_create_payload())
    assert CampaignCreate.model_validate(cc.model_dump()) == cc


def test_hypothesis_blank_rejected() -> None:
    payload = _campaign_create_payload()
    payload["hypothesis"] = "   "
    with pytest.raises(ValueError, match="REFORMS"):
        CampaignCreate(**payload)


def test_hypothesis_empty_rejected() -> None:
    payload = _campaign_create_payload()
    payload["hypothesis"] = ""
    with pytest.raises(ValueError, match="REFORMS"):
        CampaignCreate(**payload)


def test_hypothesis_stripped() -> None:
    payload = _campaign_create_payload()
    payload["hypothesis"] = "   the question   "
    cc = CampaignCreate(**payload)
    assert cc.hypothesis == "the question"


# ---------- CampaignAck / Campaign / CampaignTreeView ----------


def test_campaign_ack_minimal() -> None:
    ack = CampaignAck(
        campaign_id="c-1", run_count=4, status="started", poll="/campaigns/c-1"
    )
    assert ack.flow_run_id is None


def test_campaign_record_round_trip() -> None:
    record = {
        **_campaign_create_payload(),
        "id": "c-1",
        "status": "running",
        "runs": [
            {"run_id": "r-1", "params": {"seed": 1, "language": "python"}, "status": "running"},
            {"run_id": "r-2", "params": {"seed": 2, "language": "bash"}, "status": "queued"},
        ],
        "created_at": "2026-05-07T00:00:00",
        "updated_at": "2026-05-07T00:01:00",
        "completed_at": None,
    }
    c = Campaign.model_validate(record)
    assert len(c.runs) == 2
    assert c.runs[0].run_id == "r-1"
    assert c.status == "running"


def test_campaign_template_placeholders_preserved() -> None:
    """Placeholders are NOT validated client-side — they're filled by the server."""
    tpl = CampaignTemplate(**_campaign_template_payload())
    assert "{seed}" in tpl.project_name
    assert "{language}" in tpl.prompt


def test_campaign_run_defaults() -> None:
    cr = CampaignRun(run_id="r-1", params={"seed": 1})
    assert cr.status == "queued"
    assert cr.score is None


def test_campaign_tree_view_round_trip() -> None:
    tree_payload = {
        "campaign": {
            **_campaign_create_payload(),
            "id": "c-1",
            "status": "running",
            "runs": [],
            "created_at": "2026-05-07T00:00:00",
            "updated_at": "2026-05-07T00:01:00",
            "completed_at": None,
        },
        "runs": [
            {"run_id": "r-1", "params": {"seed": 1}, "phase": "executing", "score": None, "completed": False},
        ],
    }
    tv = CampaignTreeView.model_validate(tree_payload)
    assert len(tv.runs) == 1
    assert tv.runs[0].phase == "executing"


def test_campaign_tree_run_ignores_extras() -> None:
    """Server may stamp future fields onto tree rows; client should not reject."""
    tree_run = CampaignTreeRun(
        run_id="r-1",
        params={},
        phase="executing",
        completed=False,
        unknown_field="ignored",  # type: ignore[call-arg]
    )
    assert tree_run.run_id == "r-1"


# ---------- CampaignControlAck ----------


def test_campaign_pause_ack() -> None:
    ack = CampaignControlAck(campaign_id="c-1", flow_run_id="f-1", paused=True)
    assert ack.aborted is None


def test_campaign_abort_ack() -> None:
    ack = CampaignControlAck(campaign_id="c-1", flow_run_id="f-1", aborted=True)
    assert ack.paused is None


# ---------- VerifyResult mirrors ----------


def test_run_verify_result_round_trip() -> None:
    rv = RunVerifyResult(run_id="r-1", valid=True, status="ok", mismatches=[])
    assert rv.valid is True
    assert rv.status == "ok"


def test_run_verify_corrupted() -> None:
    rv = RunVerifyResult(
        run_id="r-1",
        valid=False,
        status="corrupted",
        mismatches=["sha256 mismatch on artifacts/output.json"],
    )
    assert rv.valid is False
    assert "sha256" in rv.mismatches[0]


def test_campaign_verify_result_round_trip() -> None:
    cv = CampaignVerifyResult(
        campaign_id="c-1", valid=True, status="ok", mismatches=[]
    )
    assert cv.valid is True
