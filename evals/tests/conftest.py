"""Shared fixtures and builders for the P8-06 eval-harness acceptance tests
(EFF-07; PRD 19.1-19.3, 19.5, 6.6, 3.5). Ticket spec: the SE orchestrator's
"## P8-06" section fixes tilo_evals's public names, file locations and
defaults so the builder implements exactly what these tests import.

Run with `uv run pytest "evals/tests" -q` from the repo root. pytest, pyyaml,
jsonschema and referencing are root dev dependencies (root pyproject.toml
[dependency-groups].dev), so `uv sync --all-packages` already provides
everything these tests import, once tilo_evals itself exists.

This directory has no __init__.py, so pytest's default "prepend" import mode
puts it on sys.path when collecting any test_*.py here -- the same
plain-module-import pattern packages/providers/tests and tests/contracts use
for their own conftest.py / _lib.py.

Per the P8-06 spec: "Build fake cases and recordings in tmp_path, not in
evals/cases." Nothing under evals/cases or evals/recordings is committed by
this branch; every case, recording and config file a test needs is written
under tmp_path (see write_case / write_recording / write_evals_config /
fake_repo below).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def fake_ulid(n: int) -> str:
    """A fake but tilo_contracts.Ulid-shaped id (^[0-7][0-9A-HJKMNP-TV-Z]{25}$,
    26 chars): hex digits (0-9A-F) are all valid Crockford base32 characters
    (no I/L/O/U), so a zero-padded hex counter always matches.
    """
    return f"01JEVAL{n:019X}"


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


def make_event(
    *,
    seq: int,
    type: str = "world.started",  # noqa: A002 -- matches the contract field name
    actor: str = "system",
    target: str = "w_eval",
    world_id: str = "w_eval",
    run_id: str = "r_eval_1",
    data: dict[str, Any] | None = None,
    authz: dict[str, Any] | None = None,
    severity: str = "info",
    credits: float = 0.0,
    summary: str = "Fixture event for the P8-06 eval-harness tests.",
    trace: dict[str, Any] | None = None,
) -> dict:
    """A minimal but contracts/event.schema.json-shaped TiloEvent dict (PRD
    9.3), for building fake recordings without a real run. Defaults produce a
    side-effect-free, unauthorised, untraced event; callers override only the
    fields their case needs.
    """
    return {
        "v": "1.0",
        "id": fake_ulid(seq),
        "seq": seq,
        "ts": "2026-10-01T00:00:00.000Z",
        "world_id": world_id,
        "run_id": run_id,
        "type": type,
        "actor": actor,
        "target": target,
        "level": None,
        "district": None,
        "item": None,
        "severity": severity,
        "credits": credits,
        "summary": summary,
        "cause": None,
        "vis": "all",
        "authz": authz,
        "data": data if data is not None else {},
        "trace": trace
        if trace is not None
        else {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
    }


def write_recording(
    path: pathlib.Path,
    events: list[dict],
    *,
    outputs: dict[str, Any] | None = None,
    credits: float | None = None,
) -> pathlib.Path:
    """Writes a ReplayExecutor recording: one TiloEvent JSON object per line,
    plus an optional final {"outputs": {...}, "credits": n} line (P8-06
    spec). write_bytes(...encode()) avoids Windows CRLF (see
    .claude/agent-memory/architect/contract-pitfalls.md).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event) for event in events]
    if outputs is not None or credits is not None:
        lines.append(json.dumps({"outputs": outputs or {}, "credits": credits if credits is not None else 0.0}))
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    return path


def write_case(
    cases_root: pathlib.Path,
    *,
    case_id: str,
    group: str,
    title: str = "Fixture case",
    measures: list[str] | None = None,
    status: str = "ready",
    deploy_gate: bool = False,
    inputs: dict[str, Any] | None = None,
    scripted_answers: list[dict[str, str]] | None = None,
    ground_truth: dict[str, Any] | None = None,
    checks: list[dict[str, Any]] | None = None,
    recording: str | None = None,
    filename: str | None = None,
) -> pathlib.Path:
    """Writes one evals/cases/<group>/<id>.yaml file (P8-06 case.schema.json
    shape) under cases_root, and returns its path. Callers building an
    intentionally malformed case (bad id, group/directory mismatch, ...) pass
    filename to control where it lands independently of case_id/group.
    """
    body: dict[str, Any] = {
        "id": case_id,
        "group": group,
        "title": title,
        "measures": measures if measures is not None else ["EFF-07"],
        "status": status,
        "deploy_gate": deploy_gate,
        "inputs": inputs if inputs is not None else {},
        "scripted_answers": scripted_answers if scripted_answers is not None else [],
        "ground_truth": ground_truth,
        "checks": checks if checks is not None else [{"check": "no_side_effects", "args": {}}],
        "recording": recording,
    }
    group_dir = cases_root / group
    group_dir.mkdir(parents=True, exist_ok=True)
    case_path = group_dir / (filename or f"{case_id}.yaml")
    case_path.write_bytes(yaml.safe_dump(body, sort_keys=False).encode("utf-8"))
    return case_path


def write_evals_config(
    config_dir: pathlib.Path,
    *,
    credit_cap: dict[str, int] | None = None,
    deploy_gate_repeats: int = 3,
    cost_regression_threshold: float = 0.20,
    groups: dict[str, int] | None = None,
) -> pathlib.Path:
    """Writes a config/evals.yaml (se-spec P8-06 shape, contract-change #8)."""
    config_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "credit_cap": credit_cap if credit_cap is not None else {"full": 2000, "smoke": 200, "gate": 1000},
        "deploy_gate_repeats": deploy_gate_repeats,
        "cost_regression_threshold": cost_regression_threshold,
        "groups": groups
        if groups is not None
        else {
            "E-PLAN": 10,
            "E-RES": 10,
            "E-DOC": 6,
            "E-MAIL": 50,
            "E-CHN": 30,
            "E-ROUTE": 20,
            "E-HAND": 20,
            "E-RED": 14,
        },
    }
    path = config_dir / "evals.yaml"
    path.write_bytes(yaml.safe_dump(body, sort_keys=False).encode("utf-8"))
    return path


@pytest.fixture
def fake_repo(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """A minimal fake repo root with config/evals.yaml and an empty
    evals/cases/ tree, chdir'd into so that tilo_evals's repo-relative
    defaults (config/evals.yaml, evals/cases, evals/results.md) resolve
    inside tmp_path instead of touching the real repo (P8-06 spec: "Build
    fake cases and recordings in tmp_path, not in evals/cases"). The
    runner's own CLI (python -m tilo_evals run --pass ...) has no override
    flags for these paths, so chdir is the only way to keep it inside
    tmp_path for a test.
    """
    write_evals_config(tmp_path / "config")
    (tmp_path / "evals" / "cases").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path
