"""PL-LIVE-E2E, live run 2 of 8 Oct 2026: "STOP refused: ... provider call failed (writer role): truncated".
Both writer calls (flash-38, then flash-37) came back with 0 visible tokens: the live runner asked the writer for 1024
output tokens and the model's own thinking used all of them (Gemini counts thinking against the cap). The writer and
the specialist now ask for room for thinking plus the text, a reply cut at its cap is asked once more with twice the
room, and the long-text roles of every model file state a cap of their own. Fake provider, no network, no live call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml
from _live_e2e_lib import (
    REAL_MODELS,
    CaseFakeModel,
    FakeWorld,
    bank_case,
    live_e2e,
    network_guard,  # noqa: F401  (autouse fixture)
    request_kind,
    run_direct,
)
from tilo_providers.errors import OutputTruncatedError, truncated_message
from tilo_providers.interfaces import GenerateRequest, GenerateResponse, ModelProvider

REPO = Path(__file__).resolve().parents[2]


@dataclass
class _TruncatingWorld(FakeWorld):
    """A model whose thinking eats the cap: a role's reply is cut (0 visible tokens) unless its request has room."""

    needs: dict[str, int] = field(default_factory=dict)
    caps: list[tuple[str, int | None]] = field(default_factory=list)

    def factory(self, role: str, profile_id: str) -> ModelProvider:
        self.built.append((role, profile_id))
        return _ThinkingModel(self, role, profile_id)


class _ThinkingModel(CaseFakeModel):
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        world = self._world
        assert isinstance(world, _TruncatingWorld)
        world.caps.append((self._role, request.max_output_tokens))
        need = world.needs.get(self._role)
        if (
            need is not None
            and (request.max_output_tokens or 1024) < need
            and request_kind(request)
            not in (
                "brief",
                "approaches",
                "plan",
            )
        ):
            error = OutputTruncatedError(
                truncated_message(0, request.max_output_tokens),
                output_tokens=0,
                thinking_tokens=request.max_output_tokens,
            )
            raise error
        return super().generate(request)


def _writer_caps(world: _TruncatingWorld) -> list[int | None]:
    return [cap for role, cap in world.caps if role == "writer"]


def test_PL_LIVE_E2E_31_the_writer_and_the_specialist_are_not_asked_for_the_routers_1024(tmp_path: Path) -> None:
    module = live_e2e()

    assert module._OUT["writer"] >= 16384 and module._OUT["specialist"] >= 8192
    assert min(module._OUT.values()) >= 1024, "no role of ours is asked for the Router's 1024 or less"
    world = _TruncatingWorld(script=bank_case("B-007").director)
    report, _ = run_direct(tmp_path, world=world)
    assert report.outcome_class == "completed", report.reason
    assert set(_writer_caps(world)) == {module._OUT["writer"]}
    assert {cap for role, cap in world.caps if role == "specialist"} <= {module._OUT["specialist"]}  # none in B-007


def test_PL_LIVE_E2E_31_a_model_that_needs_more_than_1024_for_thinking_plus_the_document_now_completes(
    tmp_path: Path,
) -> None:
    world = _TruncatingWorld(script=bank_case("B-007").director, needs={"writer": 3000, "specialist": 2000})

    report, _ = run_direct(tmp_path, world=world)

    assert report.outcome_class == "completed", report.reason  # with 1024 this run ended `truncated`, as the user's did


def test_PL_LIVE_E2E_31_a_reply_cut_at_its_cap_is_asked_once_more_with_twice_the_room(tmp_path: Path) -> None:
    module = live_e2e()
    first = module._OUT["writer"]
    world = _TruncatingWorld(script=bank_case("B-007").director, needs={"writer": first + 1})

    report, _ = run_direct(tmp_path, world=world)

    assert report.outcome_class == "completed", report.reason
    attempts = _writer_caps(world)
    assert first in attempts and first * 2 in attempts, attempts
    assert max(attempts) == first * 2


def test_PL_LIVE_E2E_31_a_second_cut_is_the_failure_not_a_third_try(tmp_path: Path) -> None:
    module = live_e2e()
    world = _TruncatingWorld(script=bank_case("B-007").director, needs={"writer": 10**6})

    report, _ = run_direct(tmp_path, world=world)

    assert report.outcome_class != "completed"
    assert "truncated" in str(report.reason).lower()
    assert max(_writer_caps(world)) == module._OUT["writer"] * 2, "the doubled cap is the most it asks for"
    assert module._OUT["writer"] * 2 <= module._RETRY_OUT_MAX


@pytest.mark.parametrize("name", ["models.yaml", "models.gemini.yaml", "models.nim.yaml"])
def test_PL_LIVE_E2E_31_the_long_text_roles_of_every_model_file_state_room_for_thinking_plus_the_text(
    name: str,
) -> None:
    roles = yaml.safe_load((REPO / "config" / name).read_text(encoding="utf-8"))["roles"]

    assert roles["writer"]["max_output_tokens"] >= 16384, "a document is longer than the Router's 1024 default"
    assert roles["specialist"]["max_output_tokens"] >= 8192
    assert roles["narrator"]["max_output_tokens"] >= 4096
    assert roles["writer"].get("thinking") in ("minimal", "low"), "the writer thinks little: the cap is for the text"


def test_PL_LIVE_E2E_31_the_real_models_file_is_the_one_checked() -> None:
    assert REAL_MODELS == REPO / "config" / "models.yaml"
