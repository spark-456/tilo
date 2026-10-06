"""PL-LIVE-E2E (issue #367): the committed fixture regenerates through a fake provider with no paid-call switch.
PRD 6.6 EFF-01 (dev and CI make no paid call; only the user sets the live switch), 9.4 HR-1.

Criteria covered:
  (a) the regen script records the committed fixture byte for byte on the current config, with no live switch set
      anywhere in the process, and the committed fixture is current (an unrelated prompt or config change shows here);
  (b) `record_with_fake` refuses a real provider, a provider that does not call itself a fake, a subclass of a network
      adapter that does, and a missing factory, before any call;
  (c) the live CLI refuses without the user's switch exactly as before, and no flag turns it into the fake path;
  (d) the regen script's own source never names the switch or the record flag.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import time
from pathlib import Path
from typing import Any

import pytest
from _live_e2e_lib import (
    COMMITTED_RECORDINGS,
    REAL_PRICES,
    REFUSED_RE,
    CaseFakeModel,
    FakeWorld,
    cli_args,
    env,
    invoke_main,
    live_e2e,
    network_guard,  # noqa: F401  (autouse fixture)
    world_for,
)
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.interfaces import GenerateRequest, ModelProvider
from tilo_providers.safety import FakeSafetyProvider

REGEN = Path(__file__).resolve().parent / "regen_live_e2e_fixture.py"
CASE = "B-007"


def _regen_module() -> Any:
    spec = importlib.util.spec_from_file_location("regen_live_e2e_fixture", REGEN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _record(tmp_path: Path, factory: Any, **kwargs: Any) -> Any:
    return live_e2e().record_with_fake(
        CASE,
        fake_factory=factory,
        recordings_dir=tmp_path / "out",
        prices_path=REAL_PRICES,
        safety=FakeSafetyProvider(),
        **kwargs,
    )


def test_PL_LIVE_E2E_34_a_regen_records_the_committed_fixture_byte_for_byte_without_the_switch(
    tmp_path: Path,
) -> None:
    module = _regen_module()
    target = tmp_path / "regen" / CASE
    with env():
        assert module.main(target=target) == 0
        assert "LIVE" not in os.environ and "TILO_RECORD" not in os.environ
    assert "LIVE" not in os.environ
    committed, made = _tree(COMMITTED_RECORDINGS / CASE), _tree(target)
    assert made, "the regen wrote nothing"
    assert made == committed, "the committed fixture is stale: run evals/tests/regen_live_e2e_fixture.py and commit"


def test_PL_LIVE_E2E_34_a_the_fake_path_writes_the_synthetic_marker_and_never_reads_the_switch(
    tmp_path: Path,
) -> None:
    world = world_for(CASE, per_million_usd=0.75, delay_s=0.0)
    with env(LIVE="0", TILO_RECORD="0"):  # neither value turns the path on or off
        report = _record(tmp_path, world.factory)
    assert report.outcome_class == "completed"
    assert (tmp_path / "out" / "SYNTHETIC").is_file()
    assert any((tmp_path / "out" / "model-recordings").rglob("*.json"))


def test_PL_LIVE_E2E_35_the_fake_run_reaches_world_completed_within_a_minute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run needs tilo-api's artifact store, redactor and raw archive seams (ADR-0018 T4); the harness wires its
    own in-memory stand-ins. Unwired, no run starts and the old 600 s wait would hide it: this one fails in 60 s."""
    monkeypatch.setitem(live_e2e()._UNIT_TIMEOUT_S, "live", 60.0)
    world = world_for(CASE, per_million_usd=0.75, delay_s=0.0)
    started = time.monotonic()
    report = _record(tmp_path, world.factory)
    assert report.outcome_class == "completed", f"{report.outcome_class}: {report.reason} ({report.event_count} events)"
    assert report.events[-1]["type"] == "world.completed", [e["type"] for e in report.events][-5:]
    assert time.monotonic() - started < 60
    assert any(e["type"] == "artifact.created" for e in report.events), "no item reached the store"


def test_PL_LIVE_E2E_34_b_a_provider_that_is_not_a_fake_is_refused_before_any_call(tmp_path: Path) -> None:
    class Unmarked(CaseFakeModel):
        SYNTHETIC_FAKE = False

    world = world_for(CASE, per_million_usd=0.75, delay_s=0.0)
    with pytest.raises(live_e2e().LiveE2ERefused) as refused:
        _record(tmp_path, lambda role, profile: Unmarked(world, role, profile))
    assert refused.value.code == "not_a_fake_provider"
    assert world.calls == []
    assert not list((tmp_path / "out").rglob("*.json"))


def test_PL_LIVE_E2E_34_b_a_network_adapter_is_refused_even_when_it_claims_to_be_a_fake(tmp_path: Path) -> None:
    class Sneaky(GoogleModelProvider):
        SYNTHETIC_FAKE = True

        def __init__(self) -> None:  # builds no client: nothing here could reach a network anyway
            pass

        def generate(self, request: GenerateRequest) -> Any:
            raise AssertionError("a real adapter was called")

    with pytest.raises(live_e2e().LiveE2ERefused) as refused:
        _record(tmp_path, lambda role, profile: Sneaky())
    assert refused.value.code == "not_a_fake_provider"


def test_PL_LIVE_E2E_34_b_no_factory_and_a_plain_provider_object_are_refused(tmp_path: Path) -> None:
    module = live_e2e()
    with pytest.raises(module.LiveE2ERefused):
        _record(tmp_path, None)
    plain: Any = type("Plain", (ModelProvider,), {})
    with pytest.raises(module.LiveE2ERefused):
        _record(tmp_path, lambda role, profile: plain)
    assert not (tmp_path / "out" / "SYNTHETIC").exists()


def test_PL_LIVE_E2E_34_c_the_live_cli_still_refuses_without_the_switch(tmp_path: Path) -> None:
    world = world_for(CASE)
    with env():
        result = invoke_main(cli_args(tmp_path), world=world)
    match = REFUSED_RE.match(result.err.strip())
    assert result.code == 2 and match and match["code"] == "live_not_enabled"
    assert world.calls == []
    with env(), pytest.raises(live_e2e().LiveE2ERefused):
        live_e2e().run_live_e2e(CASE, mode="live", live_provider_factory=world.factory, prices_path=REAL_PRICES)


def test_PL_LIVE_E2E_34_c_no_cli_flag_reaches_the_fake_path(tmp_path: Path) -> None:
    for flag in ("--fake", "--record-with-fake", "--record-fake", "--synthetic"):
        with env(), pytest.raises(SystemExit) as stop:
            invoke_main([*cli_args(tmp_path), flag], world=FakeWorld(script={}))
        assert stop.value.code == 2


def test_PL_LIVE_E2E_34_d_the_regen_script_never_sets_or_names_the_switch() -> None:
    tree = ast.parse(REGEN.read_text(encoding="utf-8"))
    names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    kwargs = {k.arg for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not {"LIVE", "TILO_RECORD"} & (names | kwargs), "the regen script must not name the live switch"
    assert not {"environ", "putenv", "setenv"} & attrs
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "env" not in imported, "the regen script must not use the test environment helper"
    assert "record_with_fake" in REGEN.read_text(encoding="utf-8")
