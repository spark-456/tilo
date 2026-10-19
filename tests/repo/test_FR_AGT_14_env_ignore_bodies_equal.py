"""FR-AGT-14 (#648 follow-up): the `this` and `env_ignored` Cloud Run resources differ only in the for_each filter and
the lifecycle block, so a change to one cannot silently skip the other."""

from __future__ import annotations

import pathlib
import re

MODULE = pathlib.Path(__file__).resolve().parents[2] / "infra/modules/service/main.tf"


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


def _normal(body: str) -> list[str]:
    body = re.sub(r'resource "[^"]+" "[^"]+"', "resource", body)
    body = re.sub(r"(?s)\n\s*lifecycle\s*\{.*?\n  \}\n", "\n", body)  # the one intended difference
    body = re.sub(r"for_each\s*=.*", "for_each", body)
    return [line.strip() for line in body.splitlines() if line.strip()]


def test_FR_AGT_14_this_and_env_ignored_bodies_stay_equal() -> None:
    code = _code(MODULE.read_text(encoding="utf-8"))
    assert _normal(_resource(code, "this")) == _normal(_resource(code, "env_ignored"))
