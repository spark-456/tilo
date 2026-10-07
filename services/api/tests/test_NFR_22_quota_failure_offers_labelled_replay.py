"""NFR-22 (PRD 17.2): "Graceful degradation: model or quota failure offers labelled replays and a clear banner;
channels queue and retry." This file is the tilo-api half: what the person is told when the Director's model
fails, and what the replay-only degradation looks like on the wire.

Real routes, real `Router`, a provider that raises the provider layer's own `QuotaError` (HTTP 429, PL-02): the
router exhausts every candidate (`RouterExhaustedError`, PL-03), the route turns that into an error. NFR-22 says
the person is then offered a replay and told it is a replay, not shown a bare "problem". PRD 17.2 NFR-24 fixes the
wire shape of that offer for the replay-only switch (503, `replay_only: true`, a detail that says "replay"); this
file applies the same shape to a model or quota failure (PRD silent on the code, so 502 and 503 are both allowed).

No network, no paid call: the scripted provider is a fake.
"""

from __future__ import annotations

from _clint1_lib import APPROACHES_REPLY, RoleScriptedProvider, brief_reply, build_router
from _sec16_lib import JUDGE_A, JUDGE_B
from tilo_providers.errors import QuotaError

DEGRADED = (502, 503)  # the PRD fixes no code; "a model failure the person can see", never 2xx and never a crash


class QuotaProvider(RoleScriptedProvider):
    """Every model call is answered 429: the daily quota of the model account is spent."""

    def generate(self, request):
        self.calls.append(request)
        raise QuotaError("PL-02: 429 quota exhausted (fake)")


def _says_replay(response) -> bool:
    body = response.json()
    return "replay" in str(body.get("detail") or body.get("error") or "").lower()


def _quota_router(repo_root):
    provider = QuotaProvider(brief_reply([]), APPROACHES_REPLY)
    return build_router(repo_root, provider), provider


def test_NFR_22_quota_failure_at_intake_offers_a_labelled_replay(clear_flow, repo_root):
    clear_flow.router, provider = _quota_router(repo_root)

    response = clear_flow.intake()

    assert provider.calls, "the failure must come from the real path: the Director's call went to the provider"
    assert response.status_code in DEGRADED, response.text
    assert _says_replay(response), f"the person is offered a replay, labelled as one (PRD 17.2 NFR-22): {response.text}"
    assert response.json().get("replay_only") is True, "the flag the web reads, as in the NFR-24 refusal"
    assert clear_flow.store.worlds == {}, "a failed intake stores nothing"


def test_NFR_22_quota_failure_when_proposing_approaches_offers_a_labelled_replay(clear_flow, repo_root):
    task = clear_flow.new_task()  # the brief was drafted while the model still answered
    clear_flow.router, provider = _quota_router(repo_root)

    response = clear_flow.approaches(task["task_id"])

    assert provider.calls
    assert response.status_code in DEGRADED, response.text
    assert _says_replay(response), f"quota failure while planning must offer a labelled replay: {response.text}"
    assert response.json().get("replay_only") is True


def test_NFR_22_replay_only_degradation_is_visible_as_a_label_and_a_refusal(sec16_factory):
    """The part that exists (NFR-24 with NFR-22's labels): the switch is set, `GET /access` says `models: "replay"`
    and new work is refused with `replay_only: true` and words that say replay. Nothing is presented as live."""
    h = sec16_factory(declarations={JUDGE_A: "judge", JUDGE_B: "judge"}, rate_limit_requests=1_000)
    h.flags.set("replay_only", True, reason="NFR-22 test: the model quota is spent")

    assert h.me().json() == {"declaration": "judge", "allowed": True, "models": "replay"}
    refused = h.intake()
    assert refused.status_code == 503, refused.text
    assert refused.json()["replay_only"] is True
    assert "replay" in refused.json()["detail"].lower()
    assert "live" not in h.router_modes, "no live router is built while degraded"
