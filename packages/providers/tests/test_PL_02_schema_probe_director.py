"""PL-02 follow-up 3: `just vertex-probe-schema` replays the EXACT Director request (`director_exact`: the real system
prompt, contents, JSON mode and sanitized schema, a small output cap) plus one variant per suspicious field removed,
so one cheap live run pins the 400 on a field. The variants are edits of what the adapter itself builds
(`GoogleModelProvider._config_kwargs`), never a hand copy. Offline only: an injected fake client, no live switch in the
real environment, no network; the printed lines are checked for prompt and schema text.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors as genai_errors
from tilo_providers import schema_probe
from tilo_providers.interfaces import GenerateRequest

SYSTEM_MARKER = "SYSTEM-PROMPT-MARKER"
TASK_MARKER = "TASK-TEXT-MARKER"
PROPERTY_MARKER = "PROPERTY-MARKER"
SCHEMA: dict[str, Any] = {
    "title": "Brief",
    "description": "a description",
    "type": "object",
    "properties": {
        PROPERTY_MARKER: {"title": "Goal", "type": "string"},
        "deadline": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "items": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "loose": {},
    },
    "required": [PROPERTY_MARKER, "deadline", "items"],
}
DIRECTOR = GenerateRequest(
    system=f"You are the Director. {SYSTEM_MARKER}",
    prompt=f"<<<TASK\n{TASK_MARKER}\nTASK>>>",
    json_mode=True,
    response_schema=SCHEMA,
)
LIVE_ENV = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": "demo-probe-project"}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LIVE", "GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_CLOUD_PROJECT", "GOOGLE_VERTEX_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


class _Models:
    """Fake `client.models`: a 400 when `reject_when(config)` holds, else a small reply (a stand-in for Google)."""

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
            prompt_token_count=900, candidates_token_count=20, thoughts_token_count=None, total_token_count=920
        )
        return SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=usage,
            prompt_feedback=None,
            text="{}",
            function_calls=None,
        )


def _run(argv: list[str], environ: dict[str, str], models: _Models) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = schema_probe.main(
            argv, environ=environ, schema=SCHEMA, director=DIRECTOR, client=SimpleNamespace(models=models)
        )
    return code, out.getvalue(), err.getvalue()


def _rows(out: str) -> dict[str, str]:
    return {line.split()[0].removeprefix("variant="): line for line in out.splitlines() if line.startswith("variant=")}


def _empty_property(config: Any) -> bool:  # Google stand-in: refuses any structured-output schema at all. (The real
    # causes, an untyped property, null branches and array bounds, never reach the wire any more: the sanitizer drops
    # or collapses them, see test_PL_02_untyped_schema.py; so this stands in for "the schema is the problem".)
    return getattr(config, "response_json_schema", None) is not None


def test_PL_02_director_variants_are_listed_first_and_in_order() -> None:
    names = schema_probe.DIRECTOR_VARIANT_NAMES
    assert names[0] == "director_exact" and names[-1] == "director_exact_real_cap"
    assert {
        "director_no_system",
        "director_system_no_role",
        "director_no_schema",
        "director_schema_no_empty",
        "director_schema_no_null_anyof",
        "director_schema_no_titles",
        "director_schema_no_item_bounds",
    } <= set(names)
    code, out, err = _run(["--dry-run"], {}, _Models())
    assert code == 0 and err == "", err
    plan = [line.split()[0].removeprefix("variant=") for line in out.splitlines() if line.startswith("variant=")]
    assert plan == [*names, *schema_probe.VARIANT_NAMES]


def test_PL_02_director_dry_run_sends_nothing_and_prints_no_prompt_or_schema_text() -> None:
    models = _Models()
    code, out, err = _run(["--dry-run"], {}, models)
    assert code == 0 and models.configs == []
    assert "nothing was sent" in out
    for marker in (SYSTEM_MARKER, TASK_MARKER, PROPERTY_MARKER):
        assert marker not in out + err


def test_PL_02_director_exact_is_the_adapters_own_config_with_a_small_cap() -> None:
    models = _Models(reject_when=_empty_property)
    code, out, err = _run([], LIVE_ENV, models)
    assert code == 0, err
    exact = models.configs[0]
    assert exact.system_instruction == DIRECTOR.system
    assert exact.response_mime_type == "application/json"
    assert "loose" not in exact.response_json_schema["properties"]  # the sanitizer drops the untyped property
    assert exact.max_output_tokens == 128  # the probe's cap, not the role's 16384
    assert exact.thinking_config is None  # the real brief request sends none


def test_PL_02_director_removal_variants_pin_the_cause_when_exact_is_rejected() -> None:
    models = _Models(reject_when=_empty_property)
    code, out, err = _run([], LIVE_ENV, models)
    assert code == 0, err
    rows = _rows(out)
    assert " status=rejected " in rows["director_exact"] + " " and "http=400" in rows["director_exact"]
    assert " status=rejected " in rows["director_schema_no_item_bounds"] + " "  # the sanitizer already dropped bounds
    assert " status=ok " in rows["director_no_schema"] + " "
    for name in ("director_no_system", "director_system_no_role", "director_schema_no_titles"):
        assert " status=rejected " in rows[name] + " ", rows[name]
    # the real-cap variant only runs when the small-cap replay was accepted
    assert "status=skipped_exact_rejected" in rows["director_exact_real_cap"]
    for marker in (SYSTEM_MARKER, TASK_MARKER, PROPERTY_MARKER):
        assert marker not in out + err


def test_PL_02_director_each_variant_changes_exactly_its_field() -> None:
    models = _Models(reject_when=lambda _config: True)  # every variant runs (the exact one is rejected)
    _run([], LIVE_ENV, models)
    names = schema_probe.DIRECTOR_VARIANT_NAMES[:-1]  # the real-cap one is skipped: the exact one was rejected
    by_name = dict(zip(names, models.configs[: len(names)], strict=True))
    exact = by_name["director_exact"]
    assert by_name["director_no_system"].system_instruction is None
    role_less = by_name["director_system_no_role"].system_instruction
    assert getattr(role_less, "role", "absent") is None and SYSTEM_MARKER in role_less.parts[0].text
    assert by_name["director_no_schema"].response_json_schema is None
    assert by_name["director_no_schema"].response_mime_type == "application/json"
    assert "loose" not in by_name["director_schema_no_empty"].response_json_schema["properties"]
    deadline = by_name["director_schema_no_null_anyof"].response_json_schema["properties"]["deadline"]
    assert deadline == {"type": "string"}  # nullable removed (the sanitizer sends it as nullable: true)
    assert "title" not in str(by_name["director_schema_no_titles"].response_json_schema)
    assert "maxItems" not in str(by_name["director_schema_no_item_bounds"].response_json_schema)
    for name, config in by_name.items():
        if name != "director_no_system" and name != "director_system_no_role":
            assert config.system_instruction == exact.system_instruction, name


def test_PL_02_director_removal_variants_are_skipped_when_exact_is_accepted() -> None:
    models = _Models()
    code, out, _err = _run([], LIVE_ENV, models)
    assert code == 0
    rows = _rows(out)
    assert " status=ok " in rows["director_exact"] + " "
    for name in schema_probe.DIRECTOR_VARIANT_NAMES[1:-1]:
        assert "status=skipped_exact_accepted" in rows[name], rows[name]
    # the real cap (16384) is quoted before the call: far over the 2-credit default ceiling, so it is not sent
    assert "status=skipped_ceiling" in rows["director_exact_real_cap"]
    assert all(c.max_output_tokens != 16384 for c in models.configs)


def test_PL_02_director_ceiling_is_enforced_before_each_call() -> None:
    models = _Models(reject_when=lambda _config: False)
    code, out, _err = _run(["--max-credits", "0.01"], LIVE_ENV, models)
    assert code == 0
    rows = _rows(out)
    assert all("status=skipped_ceiling" in line for line in rows.values()), rows
    assert models.configs == []
    total = float(out.splitlines()[-1].split()[1].removeprefix("credits="))
    assert total <= 0.01
