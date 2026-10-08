"""COST-FAST-1 (requirements 5 and 9): the safety screen, the principal, replay-only and failures, in Quick.

Every typed string still passes the safety screen (`deps.get_safety`, 503 without one) before any model sees it, and a
flagged text reaches no model, whichever mode and whatever the rules would have said. A signed-in principal is required.
`replay_only` (NFR-24) closes Quick like any new work (503 `replay_only: true`); a model that cannot answer (NFR-22) is
the same labelled offer; a bad reply is a 502; no `assistant` role fails closed and never falls back to the Director.
Shapes: `API_COST_FAST_1.md`. Fakes only; no network, no paid call.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml
from _api_contracts_lib import INJECTION_PHRASE, make_docx_bytes
from _clint1_lib import models_yaml
from _costfast1_lib import SIMPLE_TEXT, QuickProvider, SpyRouter
from fastapi import HTTPException
from tilo_api import app
from tilo_api import intake as intake_module
from tilo_providers.errors import ProviderError, QuotaError, RequestError, RetryableError

WORK_TEXT = "Send an email to the supplier asking for a new quote."


# --- the safety screen -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", [SIMPLE_TEXT, WORK_TEXT, "hmm"])
def test_COST_FAST_1_flagged_text_in_quick_reaches_no_model_and_is_a_422(quick_rig, text):
    """Flagged text is refused as today, before the rules read it: not an answer, not an offer."""
    response = quick_rig.ask(f"{text} {INJECTION_PHRASE}")

    assert response.status_code == 422, response.text
    assert "error" in response.json()
    assert quick_rig.calls == [] and quick_rig.provider_requests == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_flagged_file_name_in_quick_is_a_422_not_an_offer(quick_rig):
    response = quick_rig.ask(
        "What does this say?", files=[(f"{INJECTION_PHRASE}.docx", make_docx_bytes("Ordinary notes."))]
    )

    assert response.status_code == 422, response.text
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_quick_without_a_safety_provider_is_a_503_and_asks_no_model(quick_rig):
    def no_safety():
        raise HTTPException(status_code=503, detail="No safety provider is configured; nothing is screened.")

    app.dependency_overrides[intake_module.get_safety] = no_safety

    for text in (SIMPLE_TEXT, WORK_TEXT):
        response = quick_rig.ask(text)
        assert response.status_code == 503, (text, response.text)
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_safety_outage_during_quick_is_a_503_never_unflagged(quick_rig):
    quick_rig.safety_down = True

    for text in (SIMPLE_TEXT, WORK_TEXT):
        response = quick_rig.ask(text)
        assert response.status_code == 503, (text, response.text)
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_every_model_call_of_a_quick_ask_follows_the_screen(quick_rig):
    quick_rig.classifier_reply = '{"kind": "simple"}'
    for text in (SIMPLE_TEXT, "hmm", "tell me about Q3"):
        quick_rig.reset()
        assert quick_rig.ask(text).status_code == 200
        kinds = [kind for kind, _ in quick_rig.timeline]
        assert kinds[0] == "safety", (text, kinds)


# --- who may ask, and when --------------------------------------------------------------------------------------


def test_COST_FAST_1_quick_needs_a_signed_in_principal(quick_rig):
    quick_rig.flow.sign_out()

    for text in (SIMPLE_TEXT, WORK_TEXT):
        assert quick_rig.ask(text).status_code == 401
    assert quick_rig.calls == [] and quick_rig.timeline == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_json_body_is_not_read_as_today(quick_rig):
    response = quick_rig.client.post("/intake", json={"text": SIMPLE_TEXT, "mode": "quick"})

    assert response.status_code in (415, 422), response.text
    assert quick_rig.calls == []
    quick_rig.assert_nothing_stored()


@pytest.mark.parametrize("text", [SIMPLE_TEXT, WORK_TEXT])
def test_COST_FAST_1_replay_only_closes_quick_like_any_new_work(quick_rig, text):
    """NFR-24: after sign-in and before any work, the same 503 `replay_only: true` as Thinking, answer or offer."""
    quick_rig.flags.set("replay_only", True, reason="COST-FAST-1 test")

    response = quick_rig.ask(text)

    assert response.status_code == 503, response.text
    assert response.json()["replay_only"] is True
    assert quick_rig.calls == [] and quick_rig.timeline == []
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_clearing_replay_only_restores_quick(quick_rig):
    quick_rig.flags.set("replay_only", True, reason="COST-FAST-1 test")
    assert quick_rig.ask(SIMPLE_TEXT).status_code == 503
    quick_rig.flags.set("replay_only", False, reason="COST-FAST-1 test")

    assert quick_rig.ask(SIMPLE_TEXT).status_code == 200


# --- failures ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("error", [QuotaError("PL-02: 429 (fake)"), RetryableError("PL-02: 503 (fake)")])
def test_COST_FAST_1_a_model_that_cannot_answer_is_the_labelled_replay_offer_and_costs_nothing(quick_rig, error):
    """NFR-22: every candidate failing on quota or availability is a 503 `replay_only: true`, for this request only."""
    quick_rig.fail = error

    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code == 503, response.text
    body = response.json()
    assert body["replay_only"] is True and body["code"] == "model_unavailable"
    assert not quick_rig.flags.get("replay_only"), "the process-wide switch is NFR-24's, not set by one failure"
    assert "fake" not in response.text, "the provider's error text is never echoed"
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_rejected_request_is_a_502_with_no_provider_text(quick_rig):
    quick_rig.fail = RequestError("PL-02: 400 secret-looking-detail-9f2 (fake)")

    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code == 502, response.text
    assert "secret-looking-detail-9f2" not in response.text
    quick_rig.assert_nothing_stored()


def test_COST_FAST_1_a_provider_error_text_is_never_logged_with_the_question(quick_rig, caplog):
    quick_rig.fail = ProviderError("PL-02: boom (fake)")

    with caplog.at_level("DEBUG"):
        response = quick_rig.ask("What is the meaning of ZQMARK-5e1?")

    assert response.status_code in (502, 503)
    assert "ZQMARK-5e1" not in "\n".join(r.getMessage() for r in caplog.records)


def test_COST_FAST_1_without_an_assistant_role_quick_fails_closed_and_never_falls_back_to_the_director(
    quick_rig, monkeypatch, tmp_path: pathlib.Path
):
    """`just dev-api` has no `assistant` role (config/models.dev.yaml). Quick is a 503 `not_configured`, not a
    Director run, not a 500."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(models_yaml(safety_provider="fake")), encoding="utf-8")
    monkeypatch.setenv("TILO_MODELS_FILE", str(path))
    providers = load_providers_config(path, quick_rig.repo_root / "config" / "prices.yaml")
    assert "assistant" not in providers.roles
    quick_rig.flow.router = SpyRouter(
        Router(providers, provider_for_profile=lambda profile_id: QuickProvider(profile_id, quick_rig)), quick_rig
    )

    response = quick_rig.ask(SIMPLE_TEXT)

    assert response.status_code == 503, response.text
    assert not any(c.is_director or c.is_approaches for c in quick_rig.calls)
    assert quick_rig.provider_requests == []
    quick_rig.assert_nothing_stored()
