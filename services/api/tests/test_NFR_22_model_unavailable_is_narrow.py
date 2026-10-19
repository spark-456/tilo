"""NFR-22 (PRD 17.2), the other side of the labelled replay offer: only a model that could not answer (quota or
availability, on every candidate) is offered as a replay. A request the model rejected, or a reply it sent but got
wrong, is still the Director's own failure (502, no `replay_only`), and the offer never flips the process-wide
`replay_only` switch that NFR-24 owns. Fakes only, no network.
"""

from __future__ import annotations

import pytest
from _clint1_lib import APPROACHES_REPLY, RoleScriptedProvider, brief_reply, build_router
from tilo_api import deps
from tilo_providers.errors import QuotaError, RequestError, RetryableError
from tilo_providers.router import BudgetExceededError, RouterAttempt, RouterExhaustedError


class _Raising(RoleScriptedProvider):
    def __init__(self, error: Exception) -> None:
        super().__init__(brief_reply([]), APPROACHES_REPLY)
        self.error = error

    def generate(self, request):
        self.calls.append(request)
        raise self.error


class _Garbage(RoleScriptedProvider):
    def generate(self, request):
        from tilo_providers.interfaces import GenerateResponse  # noqa: PLC0415

        self.calls.append(request)
        return GenerateResponse(text="not json at all", profile_id=self.profile_id)


def _planning_error(cause: Exception) -> Exception:
    try:
        try:
            raise cause
        except Exception as inner:
            raise ValueError("planning failed") from inner
    except ValueError as outer:
        return outer


def _attempt(error_type: str | None) -> RouterAttempt:
    return RouterAttempt(profile_id="p", provider="fake", outcome="error", error_type=error_type)


def test_NFR_22_a_retryable_outage_on_every_candidate_also_offers_the_replay(clear_flow, repo_root):
    clear_flow.router = build_router(repo_root, _Raising(RetryableError("PL-02: 503 (fake)")))

    response = clear_flow.intake()

    assert response.status_code == 503, response.text
    assert response.json() == {
        "detail": deps.MODEL_UNAVAILABLE_MESSAGE,
        "replay_only": True,
        "code": "model_unavailable",
    }


def test_NFR_22_a_rejected_request_is_not_offered_as_a_replay(clear_flow, repo_root):
    clear_flow.router = build_router(repo_root, _Raising(RequestError("PL-02: 400 (fake)")))

    response = clear_flow.intake()

    assert response.status_code == 502, response.text
    assert "replay_only" not in response.json()


def test_NFR_22_a_wrong_reply_is_not_offered_as_a_replay(clear_flow, repo_root):
    clear_flow.router = build_router(repo_root, _Garbage(brief_reply([]), APPROACHES_REPLY))

    response = clear_flow.intake()

    assert response.status_code == 502, response.text
    assert "replay_only" not in response.json()


def test_NFR_22_the_offer_does_not_set_the_replay_only_switch(clear_flow, repo_root):
    clear_flow.router = build_router(repo_root, _Raising(QuotaError("PL-02: 429 (fake)")))

    assert clear_flow.intake().status_code == 503
    assert not deps.get_flag_store().get("replay_only"), "NFR-24's switch is the owner's and the spend cap's, not ours"


@pytest.mark.parametrize(
    "cause",
    [
        RouterExhaustedError("mixed", [_attempt("QuotaError"), _attempt("RequestError")]),
        RouterExhaustedError("no attempts", []),
        RouterExhaustedError("no capable candidate", [_attempt(None)]),
        BudgetExceededError("budget", [_attempt("QuotaError"), _attempt("BudgetExceededError")]),
        QuotaError("not through the router"),
    ],
    ids=["mixed", "no-attempts", "no-capability", "budget", "bare-quota"],
)
def test_NFR_22_only_an_exhausted_router_with_every_attempt_unavailable_counts(cause):
    deps.raise_if_model_unavailable(_planning_error(cause))  # does not raise


def test_NFR_22_an_exhausted_router_with_every_attempt_unavailable_counts():
    cause = RouterExhaustedError("all down", [_attempt("QuotaError"), _attempt("RetryableError")])
    with pytest.raises(deps.ModelUnavailable):
        deps.raise_if_model_unavailable(_planning_error(cause))
