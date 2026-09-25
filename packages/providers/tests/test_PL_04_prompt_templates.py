"""PL-04 (PRD 6.4): "Prompts are templates in prompts/, with optional
per-provider overrides" -- "No prompt text in code; snapshot tests per
role."

Ticket P0-04 section 5: a loader for prompts/<role>/<template>.md with an
optional per-provider override prompts/<role>/<template>.<provider>.md
taking precedence; "a simple, safe substitution (no eval)"; no prompt text
in code (these tests only ever write prompt text to temp files, never
embed any into this test module beyond the placeholder text needed to prove
substitution and precedence).

Ambiguity resolved (see report): the PRD does not name a substitution
syntax. stdlib `string.Template`'s own description is "simple, safe
substitution", almost verbatim what the ticket asks for, so these tests use
its `$name` / `${name}` placeholder syntax as the PRD's implied default.
"""

from __future__ import annotations

import pytest
from tilo_providers.prompts import PromptNotFoundError, load_prompt


def _write_template(prompts_root, role, name, text):
    role_dir = prompts_root / role
    role_dir.mkdir(parents=True, exist_ok=True)
    (role_dir / name).write_text(text, encoding="utf-8")


def test_PL_04_loads_base_template_by_role_and_name(tmp_path):
    _write_template(tmp_path, "director", "kickoff.md", "Plan the work for $goal.")

    rendered = load_prompt("director", "kickoff.md", {"goal": "a supplier comparison"}, prompts_root=tmp_path)

    assert rendered == "Plan the work for a supplier comparison."


def test_PL_04_per_provider_override_takes_precedence(tmp_path):
    _write_template(tmp_path, "director", "kickoff.md", "Base: $goal")
    _write_template(tmp_path, "director", "kickoff.google.md", "Google override: $goal")

    rendered = load_prompt("director", "kickoff.md", {"goal": "x"}, provider="google", prompts_root=tmp_path)

    assert rendered == "Google override: x"


def test_PL_04_falls_back_to_base_template_when_no_override_for_provider(tmp_path):
    _write_template(tmp_path, "director", "kickoff.md", "Base: $goal")
    # No prompts/director/kickoff.openai_compatible.md exists.

    rendered = load_prompt("director", "kickoff.md", {"goal": "x"}, provider="openai_compatible", prompts_root=tmp_path)

    assert rendered == "Base: x"


def test_PL_04_missing_template_raises_a_clear_error(tmp_path):
    (tmp_path / "director").mkdir()

    with pytest.raises(PromptNotFoundError):
        load_prompt("director", "does-not-exist.md", {}, prompts_root=tmp_path)


def test_PL_04_substitution_is_safe_not_eval(tmp_path):
    # "no eval": a variable value that looks like code must be inserted as
    # literal text, never executed.
    _write_template(tmp_path, "specialist", "note.md", "User said: $payload")
    payload = "__import__('os').system('echo pwned')"

    rendered = load_prompt("specialist", "note.md", {"payload": payload}, prompts_root=tmp_path)

    assert rendered == f"User said: {payload}"


def test_PL_04_two_roles_do_not_share_templates(tmp_path):
    _write_template(tmp_path, "director", "kickoff.md", "Director: $goal")
    _write_template(tmp_path, "specialist", "kickoff.md", "Specialist: $goal")

    director_text = load_prompt("director", "kickoff.md", {"goal": "x"}, prompts_root=tmp_path)
    specialist_text = load_prompt("specialist", "kickoff.md", {"goal": "x"}, prompts_root=tmp_path)

    assert director_text == "Director: x"
    assert specialist_text == "Specialist: x"
