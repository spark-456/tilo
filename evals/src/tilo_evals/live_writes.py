"""CL-LIVE-2: how a live run lets the real connectors write (API: services/connectors/tests/API_CL_LIVE_2.md).

The write gate of `tilo_connectors.real_writes` needs two things from the run once its artifact store exists: how to
read an item the run made (as the email or file the adapter will write), and the secret redactor for the gate card. This
module gives it both, from the run's own store and redactor, and hands the gate to the person at the terminal. The
terminal's typed `yes` (`live_topic.TerminalPerson`) is the only thing that approves a write.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from tilo_connectors.real import write_gate_of
from tilo_memory.artifacts import Scope

_EXTENSIONS = {"text/markdown": ".md", "text/plain": ".txt", "text/csv": ".csv", "application/json": ".json"}
_FALLBACK_SUBJECT = "Draft from Tilo"
_SUBJECT_MAX = 120


def store_resolver(
    store: Any, *, org_id: str, owner: str
) -> Callable[[str, Mapping[str, Any], str], Mapping[str, Any]]:
    """`resolve(world_id, {artifact_id, version}, kind)`: the stored version as the artifact the adapter reads.
    An email: the subject is the first non-empty line (heading marks dropped), the body is the whole text (BQ-CLLIVE-6).
    A file: named from its artifact id, with its stored media type. Strict UTF-8; anything unreadable raises."""

    def resolve(world_id: str, ref: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
        scope = Scope(org_id=org_id, world_id=world_id, owner=owner)
        head = store.head(scope, ref)
        if head is None:
            raise LookupError("no such version")
        record, data = head.record, store.read(scope, ref)
        media = str(record["media_type"])
        if kind == "email":
            text = data.decode("utf-8")
            first = next((line.strip().lstrip("#").strip() for line in text.splitlines() if line.strip()), "")
            return {"kind": "email", "subject": (first or _FALLBACK_SUBJECT)[:_SUBJECT_MAX], "body_text": text}
        name = f"{ref['artifact_id']}{_EXTENSIONS.get(media, '.bin')}"
        return {
            "kind": "file",
            "name": name,
            "mime_type": media,
            "content": data,
            "origin": {"kind": record["origin"]["kind"]},
        }

    return resolve


def release_writes(connectors: dict[str, Any]) -> None:
    """The run is over: drop every approval no write used (a spent one stays spent)."""
    if (gate := write_gate_of(connectors)) is not None:
        gate.clear()


def bind_writes(connectors: dict[str, Any], app: Any, person: Any, *, owner: str) -> None:
    """If `connectors` are write-gated: bind their gate to this run's store and redactor and give it to the person."""
    from tilo_api import deps  # noqa: PLC0415

    gate = write_gate_of(connectors)
    if gate is None:
        return
    overrides = app.dependency_overrides
    gate.bind(store_resolver(overrides[deps.get_artifact_store](), org_id=deps.ORG_ID, owner=owner),
              overrides[deps.get_redactor]())  # fmt: skip
    person.bind_write_gate(gate)
