"""The raw archive: append-only, hash-chained records per run (FR-MEM-04,
PRD 13.2, 15.1, 22.2 D-09). `verify_chain` detects any edit, insertion,
deletion or reordering, and a truncated/extended tail given an expected
head. Encryption at rest is the bucket's KMS key (infra, P0-07), not here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .record import VALID_KINDS, ZERO_HASH, canonical_json, format_ts, record_hash, split_jsonl
from .redact import redact

ORG_ID_RE = re.compile(r"^org_[0-9A-Za-z_]{1,48}$")
RUN_ID_RE = re.compile(r"^r_[0-9A-Za-z_]{1,48}$")


class Store(Protocol):
    """Append one JSONL line (never rewriting an existing one) and read every
    stored line back in order. `LocalDirStore` implements this for dev/test."""

    def append_line(self, org_id: str, run_id: str, line: str) -> None: ...

    def read_lines(self, org_id: str, run_id: str) -> list[str]: ...


class LocalDirStore:
    """One append-only JSONL file per run at `<root>/<org_id>/<run_id>.jsonl`."""

    def __init__(self, root: Path):
        self._root = Path(root)

    def _path(self, org_id: str, run_id: str) -> Path:
        return self._root / org_id / f"{run_id}.jsonl"

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        path = self._path(org_id, run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._heal_missing_trailing_newline(path)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")

    @staticmethod
    def _heal_missing_trailing_newline(path: Path) -> None:
        """A crash between writing a record's JSON and its trailing "\\n"
        leaves an otherwise-complete last line with no newline after it.
        `read_lines` (via `split_jsonl`) tolerates that on a plain read, so
        a reopen after such a crash succeeds -- but opening the file in
        append mode and writing straight onto it would then glue the next
        record onto that unterminated line, silently destroying a record
        that was never actually corrupt. Writing the missing newline back
        first is a no-op on an already-terminated file, and keeps every
        append on its own line no matter when the previous write died."""
        if not path.exists() or path.stat().st_size == 0:
            return
        with path.open("rb") as handle:
            handle.seek(-1, 2)
            last_byte = handle.read(1)
        if last_byte != b"\n":
            with path.open("ab") as handle:
                handle.write(b"\n")

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        path = self._path(org_id, run_id)
        if not path.exists():
            return []
        # Bytes, not text mode: text mode's universal newlines would also
        # rewrite a stray "\r". split_jsonl splits on "\n" only.
        return split_jsonl(path.read_bytes().decode("utf-8"))


def _parse_records(lines: list[str]) -> list[dict]:
    """Parses each stored line as JSON, in order. Raises ValueError naming
    the first unparseable line -- typically a truncated tail left by a
    process that died mid-append -- instead of letting a bare
    JSONDecodeError propagate or silently dropping/partially loading a
    corrupted run. Also raises ValueError (not some other exception) when a
    line parses to valid JSON that is not an object (e.g. a line rewritten
    to `null` or `[1,2]`): that is exactly the tampering case this format
    exists to catch, and it must fail the same clean way, so nothing is
    appended on top of a broken chain. Nothing is returned on failure: the
    caller's constructor never completes."""
    records: list[dict] = []
    for i, line in enumerate(lines, start=1):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"unparseable or truncated record at line {i}: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"record at line {i} is not a JSON object: {parsed!r}")
        records.append(parsed)
    return records


class RunArchive:
    """Appends redacted, hash-chained records for one run. Reopening (a new
    instance over the same store/org/run) continues the chain from the head."""

    def __init__(self, store: Store, *, org_id: str, run_id: str, clock: Callable[[], datetime] | None = None):
        # fullmatch (not match): with a trailing "$", .match() alone would
        # accept a string with an extra trailing "\n" -- $ matches just
        # before a final newline, but .match() never checks that the whole
        # string was consumed. fullmatch does.
        if not ORG_ID_RE.fullmatch(org_id):
            raise ValueError(f"invalid org_id: {org_id!r}")
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"invalid run_id: {run_id!r}")
        self._store = store
        self._org_id = org_id
        self._run_id = run_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: list[dict] = _parse_records(store.read_lines(org_id, run_id))

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
            # Round-trip the payload through the same canonical-JSON form it
            # will be stored and re-read as (e.g. a dict's non-str keys, such
            # as ints, become JSON object string keys) *before* hashing, so
            # the bytes that get hashed here are identical to the bytes a
            # later reopen/verify will re-derive from the stored line. Without
            # this, a payload like {"rows": {10: "x", 9: "y"}} hashes fine in
            # memory (sort_keys compares 9 < 10 as ints) but, after a reopen,
            # json.loads has turned those keys into the strings "10" and "9",
            # which sort the other way -- a spurious hash mismatch on a
            # record nobody tampered with.
            record["payload"] = json.loads(canonical_json(record["payload"]))
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
    """Problems with `records` as a hash chain, each naming the seq (or, for
    a record too malformed to have one, its position) that broke it: a hash
    mismatch, a broken prev_hash link, a gap, a duplicate or reordered seq,
    a foreign-run record, a non-object record, or (given `expected_head`) a
    truncated/extended tail. Never raises: a stored line rewritten to valid
    JSON that is not an object (`null`, `[1,2]`, a bare number) or that has
    an unhashable "seq" (e.g. a list) is exactly the tampering this exists
    to catch, so it is reported like any other broken link, not a crash."""
    problems: list[str] = []
    if not records:
        if expected_head is not None and expected_head != (0, ZERO_HASH):
            problems.append(f"empty chain does not match expected head {expected_head}")
        return problems

    run_id = next((rec.get("run_id") for rec in records if isinstance(rec, dict)), None)
    seen_seqs: set = set()
    prev_hash = ZERO_HASH
    expected_seq = 1

    for position, rec in enumerate(records, start=1):
        if not isinstance(rec, dict):
            problems.append(f"seq {position}: record is not a JSON object")
            continue

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

        try:
            is_duplicate = seq in seen_seqs
        except TypeError:
            problems.append(f"seq {seq}: seq is not a hashable value")
        else:
            if is_duplicate:
                problems.append(f"seq {seq}: duplicate seq")
            seen_seqs.add(seq)

        if seq != expected_seq:
            problems.append(f"seq {seq}: expected seq {expected_seq} (gap, reorder or missing record)")

        if rec.get("prev_hash") != prev_hash:
            problems.append(f"seq {seq}: broken prev_hash link")

        prev_hash = rec.get("hash", ZERO_HASH)
        expected_seq = (seq + 1) if isinstance(seq, int) else expected_seq + 1

    if expected_head is not None:
        last = records[-1]
        actual_head = (last.get("seq"), last.get("hash")) if isinstance(last, dict) else (None, None)
        if actual_head != expected_head:
            problems.append(f"seq {expected_head[0]}: tail does not match expected head (got seq {actual_head[0]})")

    return problems
