"""Fault logs for each edited module, plus real fail-closed unit and tool paths."""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from tilo_providers.diagnostics import failure_context, log_caught

ROOT = Path(__file__).resolve().parents[3]
MODULES = (
    (
        "services/harness/src/tilo_harness",
        "deliverable executor must_ask outputs question_wait quiz tool_runner verifier "
        "config skills validator schedule_store",
    ),
    ("services/api/src/tilo_api", "runs tasks cards results durable_store"),
    (
        "packages/providers/src/tilo_providers",
        "router google_adapter google_search_adapter google_speech_adapter cloud_tts_adapter "
        "gemini_live_voice_adapter model_armor_adapter vertex_eval_adapter openai_compat_adapter "
        "search safety speech replay media batch byok",
    ),
)
PATHS = [ROOT / folder / (name + ".py") for folder, names in MODULES for name in names.split()]


class PrivateFailure(RuntimeError):
    def __str__(self):
        raise AssertionError("exception text must never be read")


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_each_module_catch_logs_class_and_ids_without_error_text(path, caplog):
    """Execute every newly added logging statement with its actual exception binding.

    This isolates observability from network/storage prerequisites; behavioral faults below
    exercise the full callers as well. Compile the source statements so missing/wrong
    exception bindings are caught, rather than testing only the shared helper.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    handlers = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    checked = 0
    for handler in handlers:
        statements = [
            s
            for s in handler.body
            if isinstance(s, ast.Expr)
            and isinstance(s.value, ast.Call)
            and isinstance(s.value.func, ast.Name)
            and s.value.func.id == "log_caught"
        ]
        for statement in statements:
            caplog.clear()
            module = path.parent.name + "." + path.stem
            namespace = {
                "log_caught": log_caught,
                "__name__": module,
                handler.name: PrivateFailure("private prompt and API key"),
                "self": SimpleNamespace(run_id="run-test", world_id="world-test"),
                "unit": {"id": "unit-test"},
                "reply": "private prompt and API key",
            }
            with caplog.at_level(logging.ERROR):
                exec(compile(ast.Module(body=[statement], type_ignores=[]), str(path), "exec"), namespace)
            assert len(caplog.records) == 1
            record = caplog.records[0]
            assert record.levelno == logging.ERROR
            assert record.exc_info is None
            assert record.getMessage() == (
                "caught error run=run-test unit=unit-test world=world-test exception=PrivateFailure"
            )
            checked += 1
    assert checked, f"{path} has no tested failure log"


def test_diagnostics_context_survives_threads_and_is_reset(caplog):
    async def work():
        with failure_context(run_id="r", world_id="w", unit_id="u"):
            await asyncio.to_thread(log_caught, PrivateFailure(), __name__, {})
        log_caught(PrivateFailure(), __name__, {})

    with caplog.at_level(logging.ERROR):
        asyncio.run(work())
    assert "run=r unit=u world=w exception=PrivateFailure" in caplog.records[0].getMessage()
    assert "run=- unit=- world=- exception=PrivateFailure" in caplog.records[1].getMessage()


def test_storage_failure_has_recordable_reason_and_safe_log(caplog):
    from tilo_harness.executor import UnitOutcome, _Run

    run = object.__new__(_Run)
    run.writer = SimpleNamespace(run_id="r", world_id="w")
    run.store = {"artifacts": SimpleNamespace(), "scope": None, "recorded": None}
    with caplog.at_level(logging.ERROR), failure_context(run_id="r", world_id="w"):
        outcome, made = asyncio.run(run.keep({"id": "u"}, "worker", UnitOutcome(True, credits=-1), []))
    assert outcome.success is False and made == []
    assert outcome.reason == "a step's result could not be stored"
    assert "run=r unit=u world=w exception=ValueError" in caplog.text


def test_tool_screen_still_fails_closed_and_logs(caplog):
    from tilo_harness.tool_runner import ToolUnitRunner

    runner = object.__new__(ToolUnitRunner)

    def fail(_):
        raise PrivateFailure()

    runner._safety = SimpleNamespace(check=fail)
    with caplog.at_level(logging.ERROR):
        assert asyncio.run(runner._flagged("private prompt")) is True
    assert "exception=PrivateFailure" in caplog.text


def test_verifier_malformed_reply_is_unverified_and_logs(caplog):
    from tilo_harness.verifier import _verdict

    with caplog.at_level(logging.ERROR):
        assert _verdict("{broken private reply") == "unverified"
    assert "exception=JSONDecodeError" in caplog.text
    assert "private reply" not in caplog.text


def test_renderer_keeps_refusal_and_logs_original_class(monkeypatch, caplog):
    from tilo_harness import deliverable

    monkeypatch.setattr(deliverable, "parse_spec", lambda _: object())

    def fail(_):
        raise PrivateFailure()

    monkeypatch.setattr(deliverable, "render_pdf", fail)
    with caplog.at_level(logging.ERROR), pytest.raises(deliverable.DeliverableRefused):
        deliverable.render_output("private prompt")
    assert "exception=PrivateFailure" in caplog.text


def test_unit_context_isolated_through_real_run_plan(tmp_path, caplog):
    from test_FR_AGT_02_unit_failure_isolation import _setup
    from tilo_harness.executor import UnitOutcome, run_plan

    plan, layout, writer, store, config, skills = _setup(tmp_path, "w_context", n=2)

    class Runner:
        async def run(self, unit, context):
            await asyncio.to_thread(log_caught, PrivateFailure(), __name__, {})
            return UnitOutcome(True, "done")

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=Runner()))
    assert not result.failed
    lines = [r.getMessage() for r in caplog.records if r.name == __name__]
    assert len(lines) == 2
    assert {line.split("unit=")[1].split()[0] for line in lines} == {"U1", "U2"}
    assert all("world=w_context exception=PrivateFailure" in line for line in lines)


def test_plain_storage_reason_reaches_recorded_failure_event():
    from tilo_api.runs import Run

    recorded = []
    run = SimpleNamespace(
        run_id="r", world_id="w", _failed=False, paused=lambda: False, put=lambda *a, **kw: recorded.append(a)
    )
    Run._fail(run, "a step's result could not be stored", "u")
    assert recorded[0][0] == "world.failed"
    assert recorded[0][4] == {"reason": "a step's result could not be stored", "unit": "u"}
