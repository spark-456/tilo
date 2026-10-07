"""PROD-WIRE slice 3 (ADR-0026): the Terraform half of running tilo-api on Firestore. Code only: the user applies it.

Static checks, no terraform binary, no network (the planned values are pinned by
`infra/envs/dev/tests/prod_wire_api.tftest.hcl`; this file pins the text those values come from, and the things that
must never be there):

  * `infra/modules/service` takes optional `cpu_idle` (bool, default true) and `env` (map(string), default {}) per
    service and renders them on the container: no literal `cpu_idle = true` any more, an `env` block per entry;
  * the api entry of `infra/envs/dev/main.tf`: `max_instance_count = 1`, `cpu_idle = false`, and env exactly
    TILO_API_STORE and TILO_PEOPLE_STORE `"firestore"` plus TILO_FIRESTORE_PROJECT `var.project_id`;
  * every other service entry: no `env`, no `cpu_idle = false`;
  * no secret-looking env name or value anywhere in `infra/`, and neither `LIVE` nor `TILO_JUDGE_LIVE` is set on any
    service (live model calls are the user's switch, EFF-01).
"""

from __future__ import annotations

import pathlib
import re

OTHERS = ("harness", "channels", "connectors", "browser", "render", "sandbox-web")
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|PRIVATE)", re.I)
SECRET_VALUE = re.compile(r"(AIza|-----BEGIN|sk-[A-Za-z0-9]{8}|ghp_|xox[bp]-|\.env\b)")
LIVE_KEY = re.compile(r'^\s*"?(TILO_JUDGE_LIVE|LIVE)"?\s*[=:]', re.M)


def _tf_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in (repo_root / "infra").rglob("*.tf") if ".terraform" not in p.parts)


def _body(text: str, head: re.Pattern[str] | str) -> str:
    """The text between the braces that follow the first match of `head` (brace-matched, strings skipped)."""
    match = re.search(head, text) if isinstance(head, str) else head.search(text)
    assert match is not None, f"{head!r} not found"
    assert text[match.end() - 1] == "{", "the head pattern must end at the opening brace"
    depth, i, start = 1, match.end(), match.end()
    in_string = False
    while depth and i < len(text):
        char = text[i]
        if char == '"' and text[i - 1] != "\\":
            in_string = not in_string
        elif not in_string:
            depth += {"{": 1, "}": -1}.get(char, 0)
        i += 1
    assert depth == 0, "unbalanced braces"
    return text[start : i - 1]


def _services(repo_root: pathlib.Path) -> dict[str, str]:
    text = (repo_root / "infra/envs/dev/main.tf").read_text(encoding="utf-8")
    block = _body(text, r"cloud_run_services\s*=\s*\{")
    return {name: _body(block, re.compile(rf'^\s*"{re.escape(name)}"\s*=\s*\{{', re.M)) for name in ("api", *OTHERS)}


def _env(entry: str) -> dict[str, str] | None:
    """The `env = { ... }` map of one service entry as {name: raw value}, or None when it has none."""
    match = re.search(r"^\s*env\s*=\s*\{", entry, re.M)
    if match is None:
        return None
    inner = _body(entry, re.compile(r"^\s*env\s*=\s*\{", re.M))
    pairs = re.findall(r'^\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*=\s*(.+?)\s*(?:#.*)?$', inner, re.M)
    return {name: value.strip() for name, value in pairs}


def test_PROD_WIRE_3_the_service_module_takes_cpu_idle_and_env_per_service(repo_root: pathlib.Path) -> None:
    variables = (repo_root / "infra/modules/service/variables.tf").read_text(encoding="utf-8")
    services = _body(variables, r'variable\s+"services"\s*\{')
    assert re.search(r"\bcpu_idle\s*=\s*optional\(\s*bool\s*,\s*true\s*\)", services), "cpu_idle: optional(bool, true)"
    assert re.search(r"\benv\s*=\s*optional\(\s*map\(\s*string\s*\)\s*,\s*\{\s*\}\s*\)", services), (
        "env: optional(map(string), {})"
    )


def test_PROD_WIRE_3_the_service_module_renders_them_on_the_container_and_reports_them(repo_root: pathlib.Path) -> None:
    main = (repo_root / "infra/modules/service/main.tf").read_text(encoding="utf-8")
    assert not re.search(r"\bcpu_idle\s*=\s*true\b", main), "cpu_idle is no longer a literal true"
    assert re.search(r"\bcpu_idle\s*=\s*each\.value\.cpu_idle\b", main), "the container takes the entry's cpu_idle"
    assert re.search(r"each\.value\.env\b", main), "the container renders the entry's env"
    assert re.search(r'dynamic\s+"env"|\benv\s*\{', main), "one env block per variable on the container"
    outputs = (repo_root / "infra/modules/service/outputs.tf").read_text(encoding="utf-8")
    assert not re.search(r"\bcpu_idle\s*=\s*true\b", outputs), "the services output reports the real cpu_idle"
    assert re.search(r"\bcpu_idle\s*=\s*var\.services\[k\]\.cpu_idle\b", outputs)
    assert re.search(r"\benv\s*=\s*var\.services\[k\]\.env\b", outputs), "and the env (the tftest reads both)"


def test_PROD_WIRE_3_the_api_entry_is_one_writer_instance_without_idle_cpu(repo_root: pathlib.Path) -> None:
    api = _services(repo_root)["api"]
    assert re.search(r"^\s*max_instance_count\s*=\s*1\s*(#.*)?$", api, re.M), "max_instance_count = 1 (ADR-0026)"
    assert re.search(r"^\s*cpu_idle\s*=\s*false\s*(#.*)?$", api, re.M), "cpu_idle = false"
    assert re.search(r"^\s*min_instance_count\s*=\s*0\s*(#.*)?$", api, re.M), "min_instance_count stays 0 (PRD 6.5)"


def test_PROD_WIRE_3_the_api_env_is_exactly_the_three_firestore_switches(repo_root: pathlib.Path) -> None:
    env = _env(_services(repo_root)["api"])
    assert env == {
        "TILO_API_STORE": '"firestore"',
        "TILO_PEOPLE_STORE": '"firestore"',
        "TILO_FIRESTORE_PROJECT": "var.project_id",
    }, env


def test_PROD_WIRE_3_no_other_service_gets_an_env_or_idle_cpu_off(repo_root: pathlib.Path) -> None:
    for name, entry in _services(repo_root).items():
        if name == "api":
            continue
        assert _env(entry) is None, f"{name}: no environment variable in this slice"
        assert not re.search(r"^\s*cpu_idle\s*=\s*false\b", entry, re.M), f"{name}: keeps request-based CPU billing"


def test_PROD_WIRE_3_no_secret_looking_environment_variable_in_the_service_entries(repo_root: pathlib.Path) -> None:
    for name, entry in _services(repo_root).items():
        for key, value in (_env(entry) or {}).items():
            assert not SECRET_NAME.search(key), f"{name}: {key} looks like a secret name; secrets are not Terraform env"
            assert not SECRET_VALUE.search(value), f"{name}: {key} holds a secret-looking value"
            assert value.startswith(('"', "var.", "local.")), (
                f"{name}: {key} must be a literal or a variable, not {value}"
            )


def test_PROD_WIRE_3_live_and_judge_live_are_never_set_by_terraform(repo_root: pathlib.Path) -> None:
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        assert not LIVE_KEY.search(text), (
            f"{path.relative_to(repo_root)}: sets LIVE or TILO_JUDGE_LIVE (the user's switch)"
        )
    for name, entry in _services(repo_root).items():
        assert "LIVE" not in (_env(entry) or {}) and "TILO_JUDGE_LIVE" not in (_env(entry) or {}), name
