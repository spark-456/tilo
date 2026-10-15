"""CL-INT-1 / FR-INT-01, FR-INT-03 (PRD 7.1) through the flow's first call, `POST /intake`:
text + files in, `{task_id, brief, files, questions}` out (the TiloClient.submitIntake shape, issue #80).
The route needs a signed-in principal and takes every model call through the Router. HTTP shapes and
seams: API_CL_INT_1.md.
"""

from __future__ import annotations

import pathlib
import re
import statistics
import time

from _api_contracts_lib import errors_for, load_schema
from _clint1_lib import FLOW_USER, make_docx_bytes, make_png_bytes

_MODEL_ID = re.compile(r"gemini|gpt-|claude-|nvidia|flash-3|lite-3|llama", re.IGNORECASE)


def _files() -> list[tuple[str, bytes]]:
    return [
        ("brief.docx", make_docx_bytes("The quarterly numbers are strong.")),
        ("photo.png", make_png_bytes()),
        ("photo2.png", make_png_bytes()),
    ]


def test_FR_INT_01_flow_intake_returns_task_brief_files_and_questions(flow, repo_root, registry):
    response = flow.intake(files=_files())

    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body["task_id"], str) and body["task_id"]
    assert len(body["files"]) == 3
    assert all(f["status"] == "ok" for f in body["files"])
    assert isinstance(body["questions"], list)
    errors = errors_for(load_schema(repo_root, "brief"), body["brief"], registry)
    assert not errors, [e.message for e in errors]  # FR-INT-03: schema-valid brief, every chip present


def test_FR_INT_01_flow_intake_world_requested_names_the_signed_in_user(flow):
    body = flow.new_task()

    assert body["event"]["type"] == "world.requested"
    assert body["event"]["actor"] == FLOW_USER  # the principal, not a default local user


def test_FR_INT_01_flow_intake_requires_a_signed_in_principal(flow):
    flow.sign_out()

    response = flow.intake(files=_files())

    assert response.status_code == 401, response.text
    assert flow.provider.calls == []  # nothing was sent to a model for an unauthenticated caller


def test_FR_INT_01_flow_every_flow_route_requires_a_signed_in_principal(flow):
    flow.sign_out()

    assert flow.answers("t_any", []).status_code == 401
    assert flow.approaches("t_any").status_code == 401
    assert flow.approve("t_any", "quick", 50).status_code == 401  # 401, not 404: auth comes first


def test_FR_INT_01_flow_brief_comes_from_the_director_through_the_router(flow):
    flow.new_task()

    assert len(flow.provider.calls) == 1  # one brief extraction; no other model call at intake
    assert "supplier summary" in flow.provider.calls[0].prompt  # the task text went in as data


def test_FR_INT_01_flow_rejected_intake_makes_no_model_call(flow):
    response = flow.intake(text="x" * 4001)

    assert response.status_code == 422, response.text
    assert isinstance(response.json().get("error"), str)
    assert flow.provider.calls == []


def test_FR_INT_01_flow_api_source_names_no_model_id():
    """PL-01: no model id outside config/ and packages/providers."""
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_api"
    hits = [p.name for p in src.glob("*.py") if _MODEL_ID.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_AGY_REDS_1_meeting_voice_meter_source_names_no_model_id():
    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_api" / "meeting_voice_meter.py"
    assert not _MODEL_ID.search(src.read_text(encoding="utf-8"))


def test_FR_INT_01_flow_submit_p50_under_4s(flow):
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        response = flow.intake(files=_files())
        samples.append(time.perf_counter() - start)
        assert response.status_code == 201, response.text
        assert response.json()["brief"]

    assert statistics.median(samples) < 4.0, samples  # PRD 7.1: brief chips in <= 4 s p50
