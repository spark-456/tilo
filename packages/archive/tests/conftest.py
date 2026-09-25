"""Shared fixtures and helpers for packages/archive acceptance tests
(ticket FR-MEM-04 / FR-MEM-05 / SEC-14, PRD 13.2, 15.1, 16.1, 16.4, 16.5,
22.2 D-09).

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
import importlib.util
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

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

REPO_ROOT = Path(__file__).resolve().parents[3]

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

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
URLSAFE_ALPHABET = ALPHABET + "-_"


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


def load_secret_scan() -> ModuleType:
    """Loads scripts/secret_scan.py by path. Per the brief: "a package must
    not import from scripts/, tests may load it by path" -- this is a test
    helper, not part of tilo_archive.
    """
    path = REPO_ROOT / "scripts" / "secret_scan.py"
    spec = importlib.util.spec_from_file_location("_secret_scan_by_path", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rand_token(rng, n: int, alphabet: str = ALPHABET) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def luhn_check_digit(number_without_check: str) -> str:
    """Standard Luhn check digit for a digit string with the check digit
    appended at the end (used only to build fake, clearly-synthetic test
    card numbers at runtime -- never a literal card number in source)."""
    total = 0
    for i, ch in enumerate(reversed(number_without_check)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - (total % 10)) % 10)


def is_luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def fake_luhn_card(rng, length: int = 16) -> str:
    body = "4" + "".join(str(rng.randint(0, 9)) for _ in range(length - 2))
    card = body + luhn_check_digit(body)
    assert is_luhn_valid(card)
    return card


def fake_non_luhn_number(rng, length: int = 16) -> str:
    """A digit string the same shape as a card number but Luhn-invalid, e.g.
    an order number that must be left alone."""
    while True:
        digits = "".join(str(rng.randint(0, 9)) for _ in range(length))
        if not is_luhn_valid(digits):
            return digits


def with_separator(digits: str, sep: str, group: int = 4) -> str:
    return sep.join(digits[i : i + group] for i in range(0, len(digits), group))


def fake_jwt(rng) -> str:
    import base64

    def b64(obj: dict) -> str:
        raw = json.dumps(obj, sort_keys=True).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = b64({"alg": "HS256", "typ": "JWT"})
    payload = b64({"sub": "fake-user", "exp": 9999999999})
    signature = rand_token(rng, 43, URLSAFE_ALPHABET)
    return f"{header}.{payload}.{signature}"


def fake_bearer_header(rng) -> tuple[str, str]:
    """Returns (full "Authorization: Bearer <token>" header text, token alone)."""
    token = rand_token(rng, 40, URLSAFE_ALPHABET)
    return f"Authorization: Bearer {token}", token


@pytest.fixture
def store(tmp_path):
    from tilo_archive.archive import LocalDirStore

    return LocalDirStore(tmp_path)


@pytest.fixture
def archive(store):
    from tilo_archive.archive import RunArchive

    return RunArchive(store, org_id=ORG_ID, run_id=RUN_ID, clock=FakeClock())
