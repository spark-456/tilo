"""FR-WLD-03 / PRD 10.4, 11.4, HR-7: an outbox entry sends exactly what was authorised.

OB-01 and OB-05 (contracts/outbox.rules.md; harness validator, P0-09): the entry's id is the
outbox_id its authorising event reserved; its pinned item (artifact id and version) equals the
item that approval.requested reserved or policy.applied assessed; a sent entry emits one
data.transfer out whose artifact is that item. `broken` below is the reference check. Each file
in contracts/fixtures/outbox/crossref/ is shape-valid, and each invalid one breaks exactly the
rule its `rule` field and name state. The P0-09 validator's tests must run the same files.
"""

from __future__ import annotations

import pytest
from _lib import contracts_dir, errors_for, load_json

BASE = "https://contracts.tilo.example/"
RULES = ("OB-01", "OB-05")
CASE_KEYS = {"rule", "note", "entry", "authorised_by", "transfer"}
AUTHORISING = ("approval.requested", "policy.applied")


def _cases(repo_root, kind):
    return sorted((contracts_dir(repo_root) / "fixtures" / "outbox" / "crossref" / kind).glob("*.json"))


def _pinned(item):
    return None if item is None else (item["artifact_id"], item["version"])


def broken(case) -> set[str]:
    entry, auth, transfer = case["entry"], case["authorised_by"]["data"], case["transfer"]
    rules = set()
    if auth["outbox_id"] != entry["id"]:
        rules.add("OB-01")
    if auth["action_type"] != entry["action_type"] or _pinned(auth["item"]) != _pinned(entry["item"]):
        rules.add("OB-05")
    if (transfer is not None) != (entry["state"] == "sent"):
        rules.add("OB-05")
    if transfer is not None and (
        transfer["direction"] != "out"
        or transfer["outbox_id"] != entry["id"]
        or (transfer["connector"], transfer["action_type"]) != (entry["connector"], entry["action_type"])
        or _pinned(transfer["artifact"]) != _pinned(entry["item"])
    ):
        rules.add("OB-05")
    return rules


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_FR_WLD_03_OB_05_outbox_crossref_cases_are_shape_valid(repo_root, registry, kind):
    files = _cases(repo_root, kind)
    assert files, f"contracts/fixtures/outbox/crossref/{kind}/ must hold at least one case"
    for path in files:
        case = load_json(path)
        assert set(case) == CASE_KEYS, f"{path.name}: keys must be {sorted(CASE_KEYS)}"
        auth_type = case["authorised_by"]["type"]
        assert auth_type in AUTHORISING, f"{path.name}: authorised_by.type must be one of {AUTHORISING}"
        parts = [
            ("outbox.schema.json", case["entry"]),
            (f"events/data/{auth_type}.schema.json", case["authorised_by"]["data"]),
        ]
        if case["transfer"] is not None:
            parts.append(("events/data/data.transfer.schema.json", case["transfer"]))
        found = [e.message for ref, doc in parts for e in errors_for({"$ref": BASE + ref}, doc, registry)]
        assert not found, f"{path.name}: every part must be shape-valid, got {found[:3]}"


def test_FR_WLD_03_OB_05_valid_entries_send_what_was_authorised(repo_root):
    for path in _cases(repo_root, "valid"):
        case = load_json(path)
        assert case["rule"] is None and not broken(case), f"{path.name}: breaks {sorted(broken(case))}"


def test_FR_WLD_03_OB_05_each_invalid_entry_breaks_only_its_rule(repo_root):
    covered = set()
    for path in _cases(repo_root, "invalid"):
        case = load_json(path)
        rule = case["rule"]
        assert path.name.startswith(rule.lower().replace("-", "")), f"{path.name} must start with {rule}"
        assert broken(case) == {rule}, f"{path.name}: expected only {rule}, got {sorted(broken(case))}"
        covered.add(rule)
    assert covered == set(RULES), f"every rule needs an invalid case; missing {set(RULES) - covered}"


def test_FR_WLD_03_OB_05_save_file_entry_names_its_file(repo_root):
    saves = [load_json(p) for p in (contracts_dir(repo_root) / "fixtures" / "outbox" / "valid").glob("*.json")]
    saves = [e for e in saves if e["action_type"] == "save_file"]
    assert saves and all(e["item"] is not None for e in saves), "a save_file entry must name the file it saves"
