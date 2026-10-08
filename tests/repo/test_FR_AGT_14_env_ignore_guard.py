"""FR-AGT-14 / FR-TEAM-02: the Cloud Run env ignore is narrow and honest. Static checks; no terraform binary.

* the service module ignores `containers[0].env` only in the `env_ignored` resource, never in `this`;
* the module declares no `env` block anywhere (declared env would be silently never applied while env is ignored);
* a `moved` block keeps tilo-api's state address (no destroy and recreate);
* `ignore_env = true` is set for the api service only in the dev environment.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE = ROOT / "infra/modules/service/main.tf"
DEV = ROOT / "infra/envs/dev/main.tf"


def _code(text: str) -> str:
    return re.sub(r"(?m)^[ \t]*#.*$", "", text)


def _resource(text: str, name: str) -> str:
    start = text.index(f'resource "google_cloud_run_v2_service" "{name}" {{')
    depth = 0
    for i in range(text.index("{", start), len(text)):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[start : i + 1]
    raise AssertionError("unbalanced block")


def test_FR_AGT_14_env_ignored_only_in_flagged_resource() -> None:
    code = _code(MODULE.read_text(encoding="utf-8"))
    assert "containers[0].env" not in _resource(code, "this")
    ignored = _resource(code, "env_ignored")
    assert "template[0].containers[0].env" in ignored
    assert "v.ignore_env" in ignored and "!v.ignore_env" in _resource(code, "this")


def test_FR_AGT_14_module_declares_no_env_block() -> None:
    code = _code(MODULE.read_text(encoding="utf-8"))
    assert not re.search(r"(?m)^\s*(?:dynamic\s+\"env\"|env)\s*\{", code)


def test_FR_AGT_14_moved_block_keeps_api_address() -> None:
    code = _code(MODULE.read_text(encoding="utf-8"))
    m = re.search(r"moved\s*\{[^}]*\}", code)
    assert m is not None
    assert 'google_cloud_run_v2_service.this["api"]' in m.group(0)
    assert 'google_cloud_run_v2_service.env_ignored["api"]' in m.group(0)


def test_FR_AGT_14_ignore_env_true_for_api_only() -> None:
    code = _code(DEV.read_text(encoding="utf-8"))
    start = code.index("cloud_run_services = {")
    body = code[start : code.index("\n  }\n", start)]
    flagged = []
    for m in re.finditer(r'(?m)^    "([\w-]+)" = \{', body):
        end = body.find("\n    }\n", m.end())
        block = body[m.end() : end]
        if re.search(r"ignore_env\s*=\s*true", block):
            flagged.append(m.group(1))
    assert flagged == ["api"]
    assert len(re.findall(r"ignore_env\s*=\s*true", body)) == 1
