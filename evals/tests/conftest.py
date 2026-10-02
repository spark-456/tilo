"""Helpers for the eval tests (EFF-07): REPO_ROOT, write_case, a stand-in no_side_effects check, and for the
runner tests make_event, write_recording, write_evals_config, add_case and a fake_repo root under tmp_path."""

import json
import pathlib
from typing import Any

import pytest
import yaml
from tilo_evals import checks as checks_registry
from tilo_evals.checks import CheckResult

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEFAULTS = {"title": "Fixture case", "measures": ["EFF-07"], "status": "ready", "deploy_gate": False}
_DEFAULTS |= {"inputs": {}, "scripted_answers": [], "ground_truth": None, "recording": None}
_DEFAULTS["checks"] = [{"check": "no_side_effects", "args": {}}]


def _stub_no_side_effects(case: Any, outcome: Any) -> CheckResult:  # noqa: ARG001
    return CheckResult(passed=True)


# Part b may register a real "no_side_effects" check in tilo_evals.checks; don't clobber it with this
# loader-only stand-in (needed so a schema-valid case file can reference *a* registered check before part b lands).
if not checks_registry.is_registered("no_side_effects"):
    checks_registry.register("no_side_effects")(_stub_no_side_effects)


def write_case(cases_root: pathlib.Path, *, case_id: str, group: str, filename: str | None = None, **overrides: Any):
    body = {"id": case_id, "group": group, **_DEFAULTS, **overrides}
    case_path = cases_root / group / (filename or f"{case_id}.yaml")
    case_path.parent.mkdir(parents=True, exist_ok=True)
    case_path.write_bytes(yaml.safe_dump(body, sort_keys=False).encode("utf-8"))
    return case_path


def make_event(seq: int = 1, type: str = "world.started", **fields: Any) -> dict[str, Any]:  # noqa: A002
    """A TiloEvent-shaped dict with the fields the runner and checks read; override any via `fields`."""
    event: dict[str, Any] = {"id": f"01JEVAL{seq:019X}", "seq": seq, "type": type, "credits": 0.0, "data": {}}
    event |= {"summary": "Fixture event.", "authz": None, "trace": None}
    return event | fields


def write_recording(
    path: pathlib.Path, events: list[dict[str, Any]], *, outputs: dict[str, Any] | None = None, credits: Any = None
) -> pathlib.Path:
    """One event per line, then a {"outputs", "credits"} summary line when either is given."""
    lines = [json.dumps(e) for e in events]
    if outputs is not None or credits is not None:
        lines.append(json.dumps({"outputs": outputs or {}, "credits": credits if credits is not None else 0.0}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def write_evals_config(config_dir: pathlib.Path, *, credit_cap: dict[str, int | float] | None = None) -> pathlib.Path:
    caps = credit_cap or {"full": 2000, "smoke": 200, "gate": 1000}
    body: dict[str, Any] = {"credit_cap": caps, "deploy_gate_repeats": 3, "cost_regression_threshold": 0.2}
    body["groups"] = {"E-PLAN": 10, "E-RES": 10, "E-DOC": 6, "E-MAIL": 50, "E-CHN": 30, "E-ROUTE": 20}
    body["groups"] |= {"E-HAND": 20, "E-RED": 14}
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "evals.yaml"
    path.write_bytes(yaml.safe_dump(body, sort_keys=False).encode("utf-8"))
    return path


def add_case(root: pathlib.Path, case_id: str, events: list[dict[str, Any]] | None = None, **kwargs: Any) -> None:
    """A ready case plus its recording under `root` (a fake repo). `outputs` and `credits` go to the recording;
    `credits=None` writes no summary line; every other keyword is a case field."""
    outputs, credits = kwargs.pop("outputs", {}), kwargs.pop("credits", 1.0)
    summary = {"outputs": outputs, "credits": credits} if credits is not None else {}  # no credits: no summary line
    path = write_recording(root / "evals" / "recordings" / f"{case_id}.jsonl", events or [], **summary)
    kwargs.setdefault("ground_truth", {"ok": True})
    kwargs.setdefault("recording", path.relative_to(root).as_posix())
    write_case(root / "evals" / "cases", case_id=case_id, group=case_id.rsplit("-", 1)[0], **kwargs)


@pytest.fixture
def fake_repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A fake repo root (config/evals.yaml, evals/cases) that the CLI's repo-relative defaults resolve into."""
    write_evals_config(tmp_path / "config")
    (tmp_path / "evals" / "cases").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path
