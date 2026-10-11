"""PROD-WIRE slice 3, security round 1: `orgs/{org}/access/{uid}` holds each person's SEC-15 declaration and is
server-only. The rules name that path with `allow read, write: if false;`, in the same style as the schedules match, so
a later per-path client rule can never open it by accident (the catch-all alone would also deny it today)."""

from __future__ import annotations

import pathlib
import re


def test_PROD_WIRE_3_firestore_rules_deny_every_client_the_access_collection(repo_root: pathlib.Path) -> None:
    rules = (repo_root / "firestore.rules").read_text(encoding="utf-8")
    match = re.search(r"match\s+/orgs/\{(\w+)\}/access/\{(\w+)\}\s*\{(.*?)\}", rules, re.S)
    assert match is not None, "an explicit match for /orgs/{org}/access/{uid}"
    assert re.fullmatch(r"\s*allow\s+read\s*,\s*write\s*:\s*if\s+false\s*;\s*", match.group(3)), match.group(3)
    assert not re.search(r"allow[^;]*:\s*if\s+true", rules), "no allow-all in firestore.rules"
    assert re.search(r"match\s+/orgs/\{\w+\}/schedules/\{\w+\}", rules), "the schedules match is still there"
