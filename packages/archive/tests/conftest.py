"""Shared fixtures and helpers for packages/archive acceptance tests
(ticket FR-MEM-04, PRD 13.2, 15.1, 22.2 D-09).

`tilo_archive` does not exist yet -- these tests are written before the
package (test-writer step of the ticket loop, root CLAUDE.md). Every helper
here that touches `tilo_archive` imports it lazily, inside a function body,
so this conftest itself always collects; the ImportError shows up per test
file instead of hiding the whole directory behind one conftest failure.

This directory has no __init__.py, so pytest's default "prepend" import mode
puts it on sys.path when collecting any test_*.py here (same pattern as
packages/providers/tests/conftest.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import settings

# Timing is not a property under test here -- the property is "seq is
# strictly increasing" (test_FR_MEM_04_seq_strictly_increasing), not wall-
# clock speed. Each example does real filesystem I/O (LocalDirStore append,
# including the round-4 missing-trailing-newline check), so the 200 ms
# default deadline flaked under load rather than testing anything real --
# same fix as tests/contracts/conftest.py for PL-02's property tests.
settings.register_profile("archive", deadline=None)
settings.load_profile("archive")

ORG_ID = "org_test01"
RUN_ID = "r_test01"
OTHER_RUN_ID = "r_other01"
ZERO_HASH = "0" * 64

# contracts/event.schema.json $defs.archive_ref (only on the unmerged P0-03
# branch -- reproduced here from the ticket brief, not imported, since this
# ticket needs nothing from that branch). Record part pattern per the brief;
# run id part matches contracts/common.schema.json $defs.run_id, already on
# phase0-stack.
ARCHIVE_REF_RE = re.compile(r"^r_[0-9A-Za-z_]{1,48}/[0-9]{1,9}$")
RUN_ID_RE = re.compile(r"^r_[0-9A-Za-z_]{1,48}$")


class FakeClock:
    """Deterministic, injectable clock (brief REQUIRED BEHAVIOUR #3: "ts ...
    from an injectable clock"). Each call advances by one second so records
    get distinct, ordered timestamps without depending on wall-clock time.

    Ambiguity resolved (not specified by the brief or PRD 13.2): `clock` is
    assumed to be a zero-argument callable returning a timezone-aware UTC
    `datetime`, matching "ts (RFC 3339 UTC with ms, from an injectable
    clock)" -- the archive is expected to format it, not the clock. Logged
    in the test-writer report per root CLAUDE.md's ambiguity rule.
    """

    def __init__(self, start: datetime | None = None):
        self._t = start or datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        now = self._t
        self._t = self._t + timedelta(seconds=1)
        return now


def canonical_hash(record: dict) -> str:
    """Reimplements the canonical-JSON hash definition (brief REQUIRED
    BEHAVIOUR #3) independently of the production code under test: SHA-256
    hex of json.dumps(sort_keys=True, separators=(",", ":"),
    ensure_ascii=False, allow_nan=False) over the record without "hash".
    """
    body = {k: v for k, v in record.items() if k != "hash"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def mentions_seq(problems: list[str], seq: int) -> bool:
    """True if some problem string names `seq` as a standalone number
    (verify_chain: "a list[str] problems, each naming the seq that broke")."""
    pattern = re.compile(rf"\b{seq}\b")
    return any(pattern.search(p) for p in problems)


def identity_redactor(payload):
    """Trivial redactor for FR-MEM-04 tests: the chain is under test here,
    not redaction (FR-MEM-05 supplies the real redactor later)."""
    return payload


@pytest.fixture
def store(tmp_path):
    from tilo_archive.archive import LocalDirStore

    return LocalDirStore(tmp_path)


@pytest.fixture
def archive(store):
    from tilo_archive.archive import RunArchive

    return RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock(), redactor=identity_redactor)
