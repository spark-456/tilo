"""The generality bank's case loader (issue #272, GEN-01, GEN-05): evals/bank/<id>.yaml against bank.schema.json.

The bank is its own set, apart from the 160 cases of PRD 19.2 (`cases.py`), which it leaves alone. A change to any
case changes `bank_digest`, which `evals/bank/MANIFEST.sha256` pins: the bank is frozen, held out, and a change needs
the user's approval.
"""

import hashlib
import json
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Any

import jsonschema

from .config import CappedError, read_yaml

BANK_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "evals" / "bank.schema.json"
_MAX_SCHEMA_ERRORS = 20


class BankError(CappedError):
    """A bank case fails bank.schema.json, or a loader rule: file name, duplicate id."""


@dataclass(frozen=True)
class BankCase:
    id: str
    title: str
    domain: str
    shapes: tuple[str, ...]
    brief: str
    director: dict[str, Any]
    expect: dict[str, Any]
    path: Path
    files: tuple[dict[str, str], ...] = ()
    answers: dict[str, str | None] | None = None
    stop_after: str | None = None
    approve: dict[str, Any] | None = None
    gates: str = "approve_all"
    notes: str | None = None

    @property
    def outcome(self) -> str:
        return str(self.expect["outcome"])


def load_bank(root: str | Path = "evals/bank") -> list[BankCase]:
    root_path = Path(root)
    if not root_path.is_dir():
        return []
    validator = jsonschema.Draft202012Validator(json.loads(BANK_SCHEMA_PATH.read_text(encoding="utf-8")))
    seen: dict[str, Path] = {}
    cases: list[BankCase] = []
    for path in sorted(p for p in root_path.glob("*.yaml")):
        raw = read_yaml(path, BankError)
        case_id = raw.get("id", "<missing id>") if isinstance(raw, dict) else "<not a mapping>"
        errors = sorted(islice(validator.iter_errors(raw), _MAX_SCHEMA_ERRORS), key=lambda e: list(e.path))
        if errors:
            raise BankError(f"{path}: {case_id!r} failed the bank schema: " + "; ".join(e.message for e in errors))
        if path.name != f"{case_id}.yaml":
            raise BankError(f"{path}: {case_id!r} must be in a file named {case_id}.yaml")
        if case_id in seen:
            raise BankError(f"duplicate bank id {case_id!r}: {seen[case_id]} and {path}")
        seen[case_id] = path
        kwargs = dict(raw, shapes=tuple(raw["shapes"]), files=tuple(raw.get("files", ())))
        cases.append(BankCase(path=path, **kwargs))
    return cases


def bank_digest(root: str | Path = "evals/bank") -> str:
    """SHA-256 over every case file (sorted by name, LF newlines): what the manifest pins."""
    digest = hashlib.sha256()
    for path in sorted(Path(root).glob("*.yaml")):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()
