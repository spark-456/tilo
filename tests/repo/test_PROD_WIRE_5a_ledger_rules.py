"""PROD-WIRE slice 5a, security round 1: `orgs/{org}/ledger/{entry}` holds uid-bearing spend entries and is server-only.
The rules name that path with `allow read, write: if false;`, like the access and schedules matches, so a later
per-path client rule can never open it by accident (the catch-all alone would also deny it today)."""

from __future__ import annotations

import pathlib
import re


def test_PROD_WIRE_5a_firestore_rules_deny_every_client_the_ledger_collection(repo_root: pathlib.Path) -> None:
    rules = (repo_root / "firestore.rules").read_text(encoding="utf-8")
    match = re.search(r"match\s+/orgs/\{(\w+)\}/ledger/\{(\w+)\}\s*\{(.*?)\}", rules, re.S)
    assert match is not None, "an explicit match for /orgs/{org}/ledger/{entry}"
    assert re.fullmatch(r"\s*allow\s+read\s*,\s*write\s*:\s*if\s+false\s*;\s*", match.group(3)), match.group(3)
    assert not re.search(r"allow[^;]*:\s*if\s+true", rules), "no allow-all in firestore.rules"
    for kept in ("access", "schedules"):
        assert re.search(rf"match\s+/orgs/\{{\w+\}}/{kept}/\{{\w+\}}", rules), f"the {kept} match is still there"
