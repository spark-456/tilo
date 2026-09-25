"""The raw archive: append-only, hash-chained records per run (FR-MEM-04,
PRD 13.2, 15.1, 22.2 D-09).

Threat model covered here: tampering with a stored record (an edit, an
insertion, a deletion or a reordering), or a truncated/extended tail when
the caller supplies the run's expected head, is detected by `verify_chain`.
Encryption at rest is the Cloud Storage bucket's KMS key (infra, P0-07), not
this module.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .record import VALID_KINDS, ZERO_HASH, canonical_json, format_ts, record_hash
from .redact import redact

ORG_ID_RE = re.compile(r"^org_[0-9A-Za-z_]{1,48}$")
RUN_ID_RE = re.compile(r"^r_[0-9A-Za-z_]{1,48}$")


class Store(Protocol):
    """What `RunArchive` needs from a backing store: append one JSONL line,
    never rewriting an existing one, and read every stored line back in
    order. `LocalDirStore` implements this for dev/test; a `GcsStore` could
    too (out of scope for this ticket)."""

    def append_line(self, org_id: str, run_id: str, line: str) -> None: ...

    def read_lines(self, org_id: str, run_id: str) -> list[str]: ...


class LocalDirStore:
    """One append-only JSONL file per run at `<root>/<org_id>/<run_id>.jsonl`
    (brief REQUIRED BEHAVIOUR #5) -- the dev and test store."""

    def __init__(self, root: Path):
        self._root = Path(root)

    def _path(self, org_id: str, run_id: str) -> Path:
        return self._root / org_id / f"{run_id}.jsonl"

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        path = self._path(org_id, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        path = self._path(org_id, run_id)
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as handle:
            return [line for line in handle.read().splitlines() if line.strip()]


class RunArchive:
    """Appends redacted, hash-chained records for one run and reads them
    back. Reopening (a new instance over the same store/org/run) continues
    the chain from the stored head."""

    def __init__(self, store: Store, *, org_id: str, run_id: str, clock: Callable[[], datetime] | None = None):
        if not ORG_ID_RE.match(org_id):
            raise ValueError(f"invalid org_id: {org_id!r}")
        if not RUN_ID_RE.match(run_id):
            raise ValueError(f"invalid run_id: {run_id!r}")
        self._store = store
        self._org_id = org_id
        self._run_id = run_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: list[dict] = [json.loads(line) for line in store.read_lines(org_id, run_id)]

    def append(self, kind: str, payload: object) -> str:
        if kind not in VALID_KINDS:
            raise ValueError(f"invalid kind: {kind!r} (must be one of {VALID_KINDS})")
        seq = self._records[-1]["seq"] + 1 if self._records else 1
        prev_hash = self._records[-1]["hash"] if self._records else ZERO_HASH
        record = {
            "v": "1.0",
            "run_id": self._run_id,
            "seq": seq,
            "kind": kind,
            "ts": format_ts(self._clock()),
            "payload": redact(payload),
            "prev_hash": prev_hash,
        }
        try:
            record["hash"] = record_hash(record)
            line = canonical_json(record)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload is not archivable JSON: {exc}") from exc
        self._store.append_line(self._org_id, self._run_id, line)
        self._records.append(record)
        return f"{self._run_id}/{seq}"

    def head(self) -> tuple[int, str]:
        if not self._records:
            return (0, ZERO_HASH)
        last = self._records[-1]
        return (last["seq"], last["hash"])

    def records(self) -> list[dict]:
        return list(self._records)


def verify_chain(records: list[dict], expected_head: tuple[int, str] | None = None) -> list[str]:
    """Problems with `records` as a hash chain: a changed field (hash
    mismatch), a broken prev_hash link, a gap, a duplicate or reordered seq,
    a record from another run, and -- when `expected_head` is given -- a
    truncated or extended tail. Each problem names the seq that broke it."""
    problems: list[str] = []
    if not records:
        if expected_head is not None and expected_head != (0, ZERO_HASH):
            problems.append(f"empty chain does not match expected head {expected_head}")
        return problems

    run_id = records[0].get("run_id")
    seen_seqs: set = set()
    prev_hash = ZERO_HASH
    expected_seq = 1

    for rec in records:
        seq = rec.get("seq")
        rid = rec.get("run_id")

        if rid != run_id:
            problems.append(f"seq {seq}: record belongs to another run ({rid!r} != {run_id!r})")
            continue

        try:
            recomputed = record_hash(rec)
        except (TypeError, ValueError):
            problems.append(f"seq {seq}: record is not hashable JSON")
            continue
        if recomputed != rec.get("hash"):
            problems.append(f"seq {seq}: hash mismatch, record content changed")

        if seq in seen_seqs:
            problems.append(f"seq {seq}: duplicate seq")
        seen_seqs.add(seq)

        if seq != expected_seq:
            problems.append(f"seq {seq}: expected seq {expected_seq} (gap, reorder or missing record)")

        if rec.get("prev_hash") != prev_hash:
            problems.append(f"seq {seq}: broken prev_hash link")

        prev_hash = rec.get("hash", ZERO_HASH)
        expected_seq = (seq + 1) if isinstance(seq, int) else expected_seq + 1

    if expected_head is not None:
        actual_head = (records[-1].get("seq"), records[-1].get("hash"))
        if actual_head != expected_head:
            problems.append(f"seq {expected_head[0]}: tail does not match expected head (got seq {actual_head[0]})")

    return problems
