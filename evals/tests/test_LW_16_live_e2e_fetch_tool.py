"""LW-16 (ADR-0029): `live_e2e` runs units on the shared runner with the sandbox fetch tool, and its report says what is
still not real. Fakes only; nothing here sets the live switch."""

from __future__ import annotations

import pytest
from tilo_evals import live_e2e


def test_LW_16_live_e2e_units_are_offered_only_the_sandbox_fetch_tool_and_only_a_specialist_may_use_it() -> None:
    runner = live_e2e._UnitRunner(object(), object())  # type: ignore[arg-type]
    try:
        shared = runner._shared
        assert shared._tools.names() == {"fetch_url"}
        assert shared._role_tools == {"specialist": frozenset({"fetch_url"})}
        assert shared._safety is not None and type(shared._safety).__name__ == "FakeSafetyProvider"
    finally:
        runner.close()


def test_LW_16_faked_says_exactly_what_the_web_path_still_is_not() -> None:
    web_lines = [line for line in live_e2e.FAKED if line.startswith("web fetch")]
    assert len(web_lines) == 1
    line = web_lines[0].lower()
    assert "sandbox-web" in line and "never the internet" in line and "no skill grants" in line
    assert "model armor" in line, "the tool-result screen is the marker-list fake"
    assert len(live_e2e.FAKED) == 5 and live_e2e.FAKED[0].startswith("safety screen: trusted bank input")


def test_LW_16_the_live_gate_is_unchanged_by_the_fetch_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVE", raising=False)
    with pytest.raises(live_e2e.LiveE2ERefused):
        live_e2e.run_live_e2e("B-007", mode="live", environ={})
