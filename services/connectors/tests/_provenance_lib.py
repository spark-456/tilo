"""Test doubles and data factories for the FR-CON-10 provenance-manifest tests.

No production code (root CLAUDE.md test-writer rule): everything here builds inputs the way a
run would leave them (a real `tilo_archive.RunArchive` over a temp dir, events copied from
contracts/fixtures/events/valid/), a fake redactor, and a validator over the unchanged
contracts/manifest.schema.json. `tilo_connectors.provenance` does not exist yet; importing it in
the tests is what fails them for the right reason (see API_FR_CON_10.md).

Fake secrets are assembled at runtime (root CLAUDE.md hard rule): nothing secret-looking is in
this file's text.
"""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import pathlib
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"

ORG = "org_acme"
RUN = "r_deck_run_1"
OTHER_RUN = "r_other_run_9"
WORLD = "w_village_basic"
OWNER = "u_owner"
POLICY = "pol_weekly_report"
WRITER = "A_writer1"
OTHER_AGENT = "A_research2"

DECK = {"artifact_id": "art_quarterly_deck", "version": 2}
DECK_V1 = {"artifact_id": "art_quarterly_deck", "version": 1}
TABLE = {"artifact_id": "art_research_table", "version": 1}
DECK_BYTES = b"%PDF-1.7 fake quarterly deck bytes for FR-CON-10 tests\n"

AGENT = {"agent_id": WRITER, "role": "writer", "model_role": "writer", "profile": "flash-37"}


# ---------------------------------------------------------------------------
# Fake secrets and the fake redactor (PRD 16.1 rule 4, 16.2; MF-06)


def fake_token() -> str:
    """A GitHub-style personal token shape, assembled at runtime; never a real value."""
    return "gh" + "p_" + "".join(chr(ord("A") + (i * 7) % 26) for i in range(36))


_TOKEN_RE = re.compile("gh" + r"p_[A-Za-z0-9]{36}")


def fake_redact(text: str) -> str:
    """Stands in for the shared secret redactor (SEC-14): masks the fake token shape, leaves
    everything else unchanged, so "the redactor would change it" means "it held a secret"."""
    return _TOKEN_RE.sub("[REDACTED]", text)


# ---------------------------------------------------------------------------
# Raw archive (FR-MEM-04): the run's tool calls, as tilo_archive writes them


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_of(content: str) -> str:
    """The pinned fingerprint rule (API_FR_CON_10.md): SHA-256 of the archived content's UTF-8."""
    return "sha256:" + sha256_hex(content.encode("utf-8"))


def read_payload(kind: str, ref: str, content: str, tool: str = "fetch") -> dict[str, Any]:
    """A source-read `tool_call` payload in the shape API_FR_CON_10.md pins."""
    return {"tool": tool, "source": {"kind": kind, "ref": ref}, "content": content}


def _clock():
    start = datetime(2026, 9, 29, 9, 0, 0, tzinfo=UTC)
    counter = itertools.count()
    return lambda: start + timedelta(seconds=next(counter))


def make_archive(root: pathlib.Path, entries: list[tuple[str, Any]], run_id: str = RUN):
    """Writes `entries` ((kind, payload) pairs) to a real RunArchive under `root` and returns
    (archive_refs, records). The identity redactor stands in for FR-MEM-05's: the payloads here
    hold only what each test chose to put in them."""
    from tilo_archive import LocalDirStore, RunArchive

    archive = RunArchive(LocalDirStore(root), org_id=ORG, run_id=run_id, redactor=lambda p: p, clock=_clock())
    refs = [archive.append(kind, payload) for kind, payload in entries]
    return refs, archive.records()


# ---------------------------------------------------------------------------
# Events (contracts/fixtures/events/valid/<type>.json, re-pointed at this run)


def _fixture_event(event_type: str) -> dict[str, Any]:
    path = CONTRACTS / "fixtures" / "events" / "valid" / f"{event_type}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def ulid(n: int) -> str:
    return f"01JB5VQ{n:019d}"


def event(event_type: str, seq: int, *, run_id: str = RUN, **overrides: Any) -> dict[str, Any]:
    e = _fixture_event(event_type)
    e.update({"id": ulid(seq), "seq": seq, "run_id": run_id, "world_id": WORLD, "cause": None})
    for key, value in overrides.items():
        e[key] = copy.deepcopy(value)
    return e


def skill_loaded(seq: int, agent_id: str, skill: str, version: str, **kw: Any) -> dict[str, Any]:
    return event("skill.loaded", seq, actor=agent_id, target=agent_id, data={"skill": skill, "version": version}, **kw)


def artifact_created(seq: int, artifact: dict, agent_id: str = WRITER) -> dict[str, Any]:
    return event(
        "artifact.created",
        seq,
        actor=agent_id,
        target=artifact["artifact_id"],
        item={"kind": "document", "artifact_id": artifact["artifact_id"], "label": "Quarterly deck"},
        data={"artifact": dict(artifact)},
    )


def artifact_reviewed(seq: int, artifact: dict, result: str = "passed") -> dict[str, Any]:
    return event(
        "artifact.reviewed",
        seq,
        actor="A_v1",
        target=artifact["artifact_id"],
        data={"artifact": dict(artifact), "result": result},
    )


def approval_resolved(seq: int, at: str) -> dict[str, Any]:
    authz = {"by": "person", "ref": OWNER, "at": at}
    data = dict(_fixture_event("approval.resolved")["data"])
    data["outbox_id"] = ulid(9002)
    return event("approval.resolved", seq, actor=OWNER, authz=authz, data=data)


def transfer_out(seq: int, artifact: dict, authz: dict) -> dict[str, Any]:
    """The side-effect event that carried `artifact` out of Tilo (outbox send; HR-7, MF-04)."""
    return event(
        "data.transfer",
        seq,
        actor="A_l1",
        target="I_drive",
        item={"kind": "parcel", "artifact_id": artifact["artifact_id"], "label": "Quarterly deck"},
        authz=authz,
        data={
            "connector": "google_drive",
            "action_type": "save_file",
            "direction": "out",
            "artifact": dict(artifact),
            "outbox_id": ulid(9002),
            "risk_tier": "T2",
        },
    )


# ---------------------------------------------------------------------------
# Contract validation (contracts/manifest.schema.json, unchanged)


def _registry() -> Registry:
    resources = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


_VALIDATOR = None


def manifest_schema_errors(instance: Any) -> list[str]:
    global _VALIDATOR
    if _VALIDATOR is None:
        schema = json.loads((CONTRACTS / "manifest.schema.json").read_text(encoding="utf-8"))
        _VALIDATOR = jsonschema.Draft202012Validator(schema, registry=_registry())
    return [f"{list(e.absolute_path)}: {e.message}" for e in _VALIDATOR.iter_errors(instance)]


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (*all_strings(k), *all_strings(v))]
    if isinstance(value, list | tuple):
        return [s for v in value for s in all_strings(v)]
    return []
