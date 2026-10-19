"""CL-LIVE-1 security follow-ups for the run: a factory result is validated (a None or mock-returning factory never
runs on mocks, never labelled real); a topic run with the flag and no factory refuses before the Model Armor screen;
the faked line says the connectors are not read by any unit yet; the doc says what the scope can do."""

from __future__ import annotations

import _live_e2e_lib as lib
import pytest
from _cl_live_evals_lib import LIVE_ENV, ConnectorFactory, run_e2e, run_topic
from _live_e2e_lib import network_guard  # noqa: F401  (autouse fixture)
from tilo_providers.safety import FakeSafetyProvider


def _mocks():
    from tilo_api import dev_run

    return dev_run.mock_adapters()


@pytest.mark.parametrize("kind", ["e2e", "topic"])
@pytest.mark.parametrize("bad", ["none", "mocks", "empty"])
def test_CL_LIVE_1_a_factory_result_that_is_not_the_real_wrappers_refuses_the_run(kind, bad, tmp_path):
    world = lib.world_for("B-005" if kind == "e2e" else "B-007")
    result = {"none": None, "mocks": _mocks(), "empty": {}}[bad]
    run = run_e2e if kind == "e2e" else run_topic

    done = run(tmp_path, ["--real-connectors"], values=LIVE_ENV, factory=lambda: result, world=world)

    assert done.code == 2 and done.refused() == "real_connectors_failed", done.err
    assert world.calls == [] and "outcome=" not in done.out
    assert "connectors: real_read_only" not in done.out


def test_CL_LIVE_1_topic_with_the_flag_and_no_factory_refuses_before_the_safety_screen(tmp_path, monkeypatch):
    screened: list[str] = []
    original = FakeSafetyProvider.check

    def spy(self, text, *args, **kwargs):
        screened.append("called")
        return original(self, text, *args, **kwargs)

    monkeypatch.setattr(FakeSafetyProvider, "check", spy)
    world = lib.world_for("B-007")

    done = run_topic(tmp_path, ["--real-connectors"], values=LIVE_ENV, factory=None, world=world)

    assert done.code == 2 and done.refused() == "real_connectors_no_token", done.err
    assert screened == [], "the topic was not sent to the safety screen"
    assert world.calls == []


def test_CL_LIVE_1_the_faked_line_says_the_connectors_are_not_read_by_any_unit_yet(tmp_path):
    world = lib.world_for("B-005")
    done = run_e2e(tmp_path, ["--real-connectors"], values=LIVE_ENV, factory=ConnectorFactory(world=world), world=world)

    faked = [row for row in done.out.splitlines() if row.startswith("faked:") and "recipient" in row]
    assert faked and all("real, read-only, not read by any unit yet" in row for row in faked), done.out


def test_CL_LIVE_1_the_doc_says_the_compose_scope_can_send_and_the_wrapper_enforces_read_only():
    docs = (lib.REPO_ROOT / "docs" / "live-e2e.md").read_text(encoding="utf-8")
    assert "`gmail.compose` can send mail at the token level" in docs
    assert "read-only is enforced by the wrapper" in docs
    assert "`gmail.readonly` only until CL-LIVE-2" in docs
