"""PL-02 live-run diagnostic: `just vertex-probe-schema` sends one tiny Director-profile call per request variant, so a
400 from Google can be pinned on the schema, the JSON mode or the thinking config (about 0.1 credit in all).

Same live gate as `just vertex-smoke`: refused unless the user sets LIVE=1; `--dry-run` / `--replay` print the plan and
send nothing. These tests never set the live switch in the real environment and never touch a network: the live path
runs against an injected fake client, and the status lines are checked for leaking prompt or schema text.
"""

from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors
from tilo_providers import schema_probe

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "packages" / "providers" / "scripts" / "live_vertex_probe_schema.py"
SCHEMA_MARKER = "SCHEMA-PROPERTY-MARKER"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {SCHEMA_MARKER: {"type": "string", "maxLength": 5, "default": "x"}},
    "required": [SCHEMA_MARKER],
}
LIVE_ENV = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": "demo-probe-project"}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LIVE", "GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_VERTEX_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def _run(argv: list[str], environ: dict[str, str], **kwargs: Any) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = schema_probe.main(argv, environ=environ, schema=SCHEMA, **kwargs)
    return code, out.getvalue(), err.getvalue()


class _Models:
    """Fake `client.models`: answers 400 when `reject_when(config)` holds (a stand-in for Google)."""

    def __init__(self, reject_when: Any = None) -> None:
        self.configs: list[Any] = []
        self.reject_when = reject_when

    def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
        self.configs.append(config)
        if self.reject_when and self.reject_when(config):
            raise genai_errors.ClientError(
                400, {"error": {"code": 400, "message": "Request contains an invalid argument.", "status": "X"}}
            )
        usage = SimpleNamespace(
            prompt_token_count=100, candidates_token_count=10, thoughts_token_count=None, total_token_count=110
        )
        return SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=usage,
            prompt_feedback=None,
            text="{}",
            function_calls=None,
        )


def _rejects_raw_schema(config: Any) -> bool:
    return "maxLength" in str(getattr(config, "response_json_schema", None))


def test_PL_02_probe_refuses_without_the_live_switch_and_sends_nothing() -> None:
    models = _Models()
    for environ in ({}, {"LIVE": "0"}, {"LIVE": "true"}, {"LIVE": ""}):
        code, out, err = _run([], environ, client=SimpleNamespace(models=models))
        assert code == 2 and out == ""
        assert err.startswith("REFUSED live_not_enabled:"), err
    assert models.configs == []


def test_PL_02_probe_dry_run_prints_the_plan_and_sends_nothing() -> None:
    models = _Models()
    for flag in ("--dry-run", "--replay"):
        code, out, err = _run([flag], {}, client=SimpleNamespace(models=models))
        assert code == 0 and err == "", err
        for name in schema_probe.VARIANT_NAMES:
            assert f"variant={name} " in out
        assert "dry-run" in out and "nothing was sent" in out
        assert SCHEMA_MARKER not in out
    assert models.configs == []


def test_PL_02_probe_dry_run_refuses_when_the_live_switch_is_on() -> None:
    code, _out, err = _run(["--dry-run"], LIVE_ENV, client=SimpleNamespace(models=_Models()))
    assert code == 2 and err.startswith("REFUSED replay_with_live:")


def test_PL_02_probe_the_script_refuses_without_the_live_switch_and_dry_runs_for_free() -> None:
    import os  # noqa: PLC0415

    clean = {k: v for k, v in os.environ.items() if k not in ("LIVE", "GOOGLE_API_KEY", "GEMINI_API_KEY")}
    refused = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=clean, timeout=120)
    assert refused.returncode == 2 and refused.stderr.startswith("REFUSED live_not_enabled:"), refused.stderr
    dry = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"], capture_output=True, text=True, env=clean, timeout=120
    )
    assert dry.returncode == 0, dry.stderr
    assert "variant=schema_sanitized " in dry.stdout and "nothing was sent" in dry.stdout


def test_PL_02_probe_live_run_reports_one_status_line_per_variant_and_the_cost() -> None:
    models = _Models(reject_when=_rejects_raw_schema)
    code, out, err = _run([], LIVE_ENV, client=SimpleNamespace(models=models))
    assert code == 0 and err == "", err
    lines = out.splitlines()
    statuses = {line.split()[0].removeprefix("variant="): line for line in lines if line.startswith("variant=")}
    assert set(statuses) == set(schema_probe.VARIANT_NAMES) and len(models.configs) == len(schema_probe.VARIANT_NAMES)
    assert " status=ok " in statuses["schema_sanitized"] + " "
    assert " status=rejected " in statuses["schema_raw"] + " " and "http=400" in statuses["schema_raw"]
    assert "ClientError" in statuses["schema_raw"] or "RequestError" in statuses["schema_raw"]
    assert lines[-1].startswith("total credits=") and "ceiling=" in lines[-1]
    # the sanitized variant went out without the unsupported keywords, the raw one with them
    sent = [str(getattr(c, "response_json_schema", None)) for c in models.configs]
    assert any("maxLength" in text for text in sent) and any(
        SCHEMA_MARKER in text and "maxLength" not in text for text in sent
    )
    # no prompt or schema text in what is printed
    assert SCHEMA_MARKER not in out + err and schema_probe.PROBE_PROMPT not in out + err


def test_PL_02_probe_minimal_thinking_is_tested_unmapped_and_mapped() -> None:
    """The adapter maps minimal to low, so the variant that tests Vertex's reaction to minimal bypasses it."""
    models = _Models()
    code, out, _err = _run([], LIVE_ENV, client=SimpleNamespace(models=models))
    assert code == 0
    by_name = dict(zip(schema_probe.VARIANT_NAMES, models.configs, strict=True))

    def level(name: str) -> str:
        return str(by_name[name].thinking_config.thinking_level).upper()

    assert "MINIMAL" in level("json_mode_thinking_minimal_unmapped")
    assert level("json_mode_thinking_minimal_mapped").endswith("LOW")
    plan = {line.split()[0]: line for line in schema_probe_plan()}
    assert "thinking=minimal(sent as minimal)" in plan["variant=json_mode_thinking_minimal_unmapped"]
    assert "thinking=minimal(adapter sends low)" in plan["variant=json_mode_thinking_minimal_mapped"]


def schema_probe_plan() -> list[str]:
    _code, out, _err = _run(["--dry-run"], {}, client=SimpleNamespace(models=_Models()))
    return [line for line in out.splitlines() if line.startswith("variant=")]


def test_PL_02_probe_variants_cover_no_schema_json_mode_both_schemas_and_thinking() -> None:
    names = set(schema_probe.VARIANT_NAMES)
    assert {"no_schema", "json_mode", "schema_sanitized", "schema_raw"} <= names
    assert any("thinking" in name for name in names)


def test_PL_02_probe_caps_are_enforced() -> None:
    for argv in (["--max-output-tokens", "100000"], ["--max-credits", "100000"], ["--max-output-tokens", "0"]):
        code, _out, err = _run([*argv], LIVE_ENV, client=SimpleNamespace(models=_Models()))
        assert code == 2 and err.startswith("REFUSED cap_out_of_range:"), err


@pytest.mark.parametrize("bad", ["GOOGLE_API_KEY", "GEMINI_API_KEY"])
def test_PL_02_probe_refuses_an_api_key_like_the_smoke(bad: str) -> None:
    code, _out, err = _run([], {**LIVE_ENV, bad: "x"}, client=SimpleNamespace(models=_Models()))
    assert code == 2 and err.startswith("REFUSED api_key_present:")
