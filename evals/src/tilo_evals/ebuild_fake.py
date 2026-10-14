"""Eight E-BUILD mechanics evals, executing the existing acceptance flows without recordings.

An isolated process keeps connector test helpers' plain-module imports out of the eval runner.
Only in-memory stores and fake safety/redaction are used; sockets are refused in the child.
This proves backend card/event mechanics, not a browser render or partner activation.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .checks import Outcome
from .executors import ExecutorError

SCENARIOS = (
    "standard",
    "second_deliverable_with_a_granted_excerpt",
    "non_ascii_and_reserved_characters",
    "nothing_but_the_goal",
    "unaccepted_text",
    "ungranted_file",
    "url_length",
    "prompt_length",
)
ROOT = Path(__file__).resolve().parents[3]


def execute(case: Any) -> Outcome:
    scenario = case.inputs.get("scenario")
    if scenario not in SCENARIOS:
        raise ExecutorError(f"case {case.id}: unknown E-BUILD fake scenario")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "tilo_evals.ebuild_fake", scenario],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ExecutorError(f"case {case.id}: fake flow could not run: {exc}") from exc
    if proc.returncode:
        raise ExecutorError(f"case {case.id}: fake flow failed: {proc.stderr[-2000:]}")
    try:
        outputs = json.loads(proc.stdout)
    except ValueError as exc:
        raise ExecutorError(f"case {case.id}: malformed fake outcome") from exc
    return Outcome(events=(), outputs=outputs, credits=0.0)


def _no_network(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("E-BUILD evals forbid network calls")


def run_fake(scenario: str) -> dict[str, Any]:
    setattr(socket.socket, "connect", _no_network)
    setattr(socket.socket, "connect_ex", _no_network)
    socket.create_connection = _no_network
    socket.getaddrinfo = _no_network
    sys.path.insert(0, str(ROOT / "services/connectors/tests"))
    import test_FR_CON_16_E_BUILD_cases as existing
    from _handoff_lib import enqueue, link_url, lv, make_env, run_flow
    from tilo_connectors import OutboxRefused

    if scenario in existing.FOUR_HANDOFFS:
        existing.test_FR_CON_16_E_BUILD_a_handoff_prompt_holds_only_accepted_requirements(scenario)
        spec = existing.FOUR_HANDOFFS[scenario]()
        env = make_env()
        accepted = spec["accepted"]
        flow = run_flow(
            env,
            accepted=accepted,
            framing=existing._framing(accepted),
            grant_specs=spec["grant"],
            texts=spec.get("texts"),
        )
        # The card's artifact is the exact stored prompt; approval is T3 and a person is mandatory.
        assert flow.gate["risk_tier"] == "T3"
        assert flow.gate["item"] == flow.record.prompt
        assert env.artifacts.read(accepted.world_id, flow.gate["item"]).decode() == flow.prepared.prompt
        try:
            enqueue(env, flow.case, authorised_by=None)
        except OutboxRefused:
            pass
        else:
            raise AssertionError("T3 accepted missing person approval")
        assert env.links.links == [] and env.emitted == []
        enqueue(env, flow.case)
        assert [e["state"] for e in env.outbox.dispatch_due()] == ["sent"]
        assert lv().decode_link(link_url(env)) == flow.prepared.prompt
        transfers = env.transfers()
        assert len(transfers) == 1
        assert transfers[0]["data"]["artifact"] == flow.gate["item"]
        assert transfers[0]["data"]["risk_tier"] == "T3"
        assert transfers[0]["authz"] is not None
    elif scenario == "unaccepted_text":
        existing.test_FR_CON_16_E_BUILD_planted_unaccepted_text_has_zero_leaks_in_the_prompt_the_link_and_the_events()
    elif scenario == "ungranted_file":
        existing.test_FR_CON_20_E_BUILD_a_planted_ungranted_file_has_zero_leaks_and_is_never_read()
    else:
        with tempfile.TemporaryDirectory(prefix="tilo-ebuild-") as folder:
            if scenario == "url_length":
                existing.test_FR_CON_17_E_BUILD_an_over_long_brief_by_url_length_gives_brief_too_long_with_the_mcp_offer(
                    Path(folder)
                )
            elif scenario == "prompt_length":
                existing.test_FR_CON_17_E_BUILD_an_over_long_brief_by_prompt_characters_gives_brief_too_long_with_the_mcp_offer(
                    Path(folder)
                )
            else:
                raise ValueError("unknown fake scenario")
    return {"scenario": scenario, "mechanics_passed": True, "basis": "scripted_fakes"}


if __name__ == "__main__":
    print(json.dumps(run_fake(sys.argv[1])))
