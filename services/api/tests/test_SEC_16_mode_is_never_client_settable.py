"""SEC-16 (with SEC-15), a guard on the live path: `get_plan_compiler`, `get_unit_runner` and `get_must_ask_providers`
take a `mode` parameter (default "replay"). Used directly as a FastAPI `Depends`, that parameter would become a
client-settable query parameter and a request could ask for "live". They are only ever called by `runs.run_seams`,
which passes the mode `access.provider_mode` decided. Two checks, one on the source and one on the served API:

* no `Depends(...)` anywhere in tilo-api names one of the three (nor any function that takes a `mode` the client could
  set);
* no operation in `app.openapi()` has a parameter named `mode` (query, header, cookie or path), and no request body
  schema has a `mode` property.

These pass today: they are a regression guard for the SEC-16 wiring, which touches exactly these seams.
"""

from __future__ import annotations

import ast
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
API_SRC = REPO_ROOT / "services" / "api" / "src" / "tilo_api"
MODE_SEAMS = {"get_plan_compiler", "get_unit_runner", "get_must_ask_providers"}


def _name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_SEC_16_no_route_uses_a_mode_seam_directly_as_a_dependency():
    offenders = []
    for path in sorted(API_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _name(node.func) in {"Depends", "Security"}:
                for arg in [*node.args, *(k.value for k in node.keywords)]:
                    if _name(arg) in MODE_SEAMS:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}: Depends({_name(arg)})")
    assert offenders == [], f"a client could set `mode`: {offenders}"


def test_SEC_16_no_served_operation_takes_a_mode_parameter_from_the_client():
    from tilo_api import app

    spec = app.openapi()
    offenders = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                if parameter["name"].lower() == "mode":
                    offenders.append(f"{method.upper()} {path}: {parameter['in']} parameter `mode`")
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        if "mode" in schema.get("properties", {}) and name.endswith(("In", "Body", "Request")):
            offenders.append(f"request schema {name} has a `mode` property")
    assert offenders == [], f"a client could set `mode`: {offenders}"
