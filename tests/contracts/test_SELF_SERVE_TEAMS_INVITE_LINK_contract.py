"""SELF-SERVE-TEAMS INVITE-LINK (ADR-0046): signed, single-use, expiring team invite links.

`team_invite_link.schema.json` 1.0.0 is the stored link (no token, nonce, signature or URL); registry 1.6.0 adds
`invite_link.created`, `invite_link.accepted` and `invite_link.revoked`; people.rules.md adds PE-38 and PE-39 and
amends PE-37 (a person leaves an entry they accepted). `_invite_link_lib.link_permits` is the reference check for
`contracts/fixtures/team_invite_link/crossref/`, which the `tilo_people` and `tilo-api` suites run once built.
"""

from __future__ import annotations

import _invite_link_lib as il
import _people_lib as pl
import pytest
import yaml

TYPES = ("invite_link.created", "invite_link.accepted", "invite_link.revoked")
LINK = {
    "id": "til_0a1b2c3d4e5f60718293a4b5",
    "org_id": "org_example",
    "team": "tm_launch",
    "created_by": {"by": "u_lena", "at": "2026-10-15T08:40:00.000Z"},
    "expires_at": "2026-10-22T08:40:00.000Z",
    "key_id": "key_a",
    "nonce_sha256": "0" * 64,
    "status": "pending",
    "redeemed": None,
    "revoked": None,
}
STAMP = {"by": "u_ravi", "at": "2026-10-15T09:00:00.000Z"}


def _cases(repo_root, kind):
    cases = il.load_cases(repo_root, kind)
    assert cases, f"contracts/fixtures/team_invite_link/crossref/{kind}/ must hold at least one case"
    return cases


def test_SELF_SERVE_TEAMS_INVITE_LINK_schema_is_closed_and_keeps_no_secret(repo_root, registry):
    schema = pl.load_contract(repo_root, "team_invite_link")
    assert schema["x-version"] == "1.0.0" and schema["title"] == "TeamInviteLink"
    assert schema["additionalProperties"] is False
    assert not {"token", "nonce", "signature", "url", "key"} & set(schema["properties"])
    pl.assert_valid(repo_root, registry, "team_invite_link", LINK)
    for extra in ({"token": "v1.key_a.x"}, {"url": "https://example.com/join"}, {"nonce": "AAAA"}):
        pl.assert_invalid(repo_root, registry, "team_invite_link", {**LINK, **extra}, why=str(extra))


@pytest.mark.parametrize(
    ("status", "redeemed", "revoked", "ok"),
    [
        ("pending", None, None, True),
        ("pending", STAMP, None, False),
        ("pending", None, STAMP, False),
        ("redeemed", STAMP, None, True),
        ("redeemed", None, None, False),
        ("redeemed", STAMP, STAMP, False),
        ("revoked", None, STAMP, True),
        ("revoked", None, None, False),
        ("revoked", STAMP, STAMP, False),
        ("expired", None, None, False),
    ],
)
def test_SELF_SERVE_TEAMS_INVITE_LINK_PE_38_each_status_carries_only_its_own_stamp(
    repo_root, registry, status, redeemed, revoked, ok
):
    link = {**LINK, "status": status, "redeemed": redeemed, "revoked": revoked}
    check = pl.assert_valid if ok else pl.assert_invalid
    check(repo_root, registry, "team_invite_link", link, why=f"{status} {redeemed} {revoked}")


@pytest.mark.parametrize("digest", ["0" * 63, "A" * 64, "0" * 64 + "\n", "g" * 64])
def test_SELF_SERVE_TEAMS_INVITE_LINK_PE_38_the_digest_is_64_lowercase_hex(repo_root, registry, digest):
    pl.assert_invalid(repo_root, registry, "team_invite_link", {**LINK, "nonce_sha256": digest}, why=repr(digest))


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_SELF_SERVE_TEAMS_INVITE_LINK_crossref_cases_are_shape_valid(repo_root, registry, kind):
    for path, case in _cases(repo_root, kind):
        found = il.case_shape_problems(repo_root, registry, case)
        assert not found, f"{kind}/{path.name}: {found[:3]}"


def test_SELF_SERVE_TEAMS_INVITE_LINK_every_valid_case_is_granted(repo_root):
    for path, case in _cases(repo_root, "valid"):
        assert case["rule"] is None, f"valid/{path.name}: rule must be null"
        assert il.link_permits(case), f"valid/{path.name}: refused, must be granted: {case['note']}"


def test_SELF_SERVE_TEAMS_INVITE_LINK_every_invalid_case_is_refused_and_named_after_its_rule(repo_root):
    for path, case in _cases(repo_root, "invalid"):
        assert case["rule"] in il.RULES, f"invalid/{path.name}: rule must be one of {il.RULES}"
        assert path.name.startswith(case["rule"].lower().replace("-", "") + "_"), f"invalid/{path.name}"
        assert not il.link_permits(case), f"invalid/{path.name}: granted, must be refused: {case['note']}"


def test_SELF_SERVE_TEAMS_INVITE_LINK_every_rule_and_action_has_both_kinds_of_case(repo_root):
    invalid = [case for _, case in _cases(repo_root, "invalid")]
    valid = [case for _, case in _cases(repo_root, "valid")]
    assert {case["rule"] for case in invalid} == set(il.RULES)
    for action in il.NEEDS:
        assert any(c["request"]["action"] == action for c in valid), f"no valid case for {action}"
        assert any(c["request"]["action"] == action for c in invalid), f"no invalid case for {action}"


def test_SELF_SERVE_TEAMS_INVITE_LINK_registry_has_three_ids_only_desk_events(repo_root, registry):
    raw = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    assert tuple(int(p) for p in str(raw["version"]).split(".")) >= (1, 6, 0)
    for type_ in TYPES:
        entry = raw["types"][type_]
        assert entry["family"] == "invite_link" and entry["side_effect"] is False and "authz_by" not in entry
        data = pl.load_contract(repo_root, f"events/data/{type_}")
        assert data["additionalProperties"] is False
        assert set(data["properties"]) <= {"invite_id", "team", "expires_at"}, "ids and the expiry only"
        sample = {"invite_id": LINK["id"], "team": "tm_launch", "expires_at": LINK["expires_at"]}
        sample = {k: v for k, v in sample.items() if k in data["properties"]}
        pl.assert_valid(repo_root, registry, f"events/data/{type_}", sample)
        pl.assert_invalid(repo_root, registry, f"events/data/{type_}", {**sample, "token": "v1.x"})


def test_SELF_SERVE_TEAMS_INVITE_LINK_rules_and_adr_record_the_owners_approval(repo_root):
    rules = (pl.contracts_dir(repo_root) / "people.rules.md").read_text(encoding="utf-8")
    assert "| PE-38 |" in rules and "| PE-39 |" in rules and "ADR-0046" in rules
    adr = next((repo_root / "docs" / "adr").glob("0046-*.md")).read_text(encoding="utf-8")
    assert "Sure go on" in adr, "the ADR records the owner's approval in their words"
