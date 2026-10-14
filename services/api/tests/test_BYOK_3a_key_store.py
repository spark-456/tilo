"""BYOK-3a (ADR-0041 decision 2): the key reference, the audit entries, the act limiter and the in-memory vault.

The vault here is the connectors double of the ADR's slice; fake secrets are assembled at runtime and nothing leaves
the process. The routes that use these are in `test_BYOK_3a_org_model_key_routes.py`."""

from __future__ import annotations

import json
import secrets

import pytest
from tilo_api.byok_store import (
    ACTS_PER_HOUR,
    SLOT,
    KeyReference,
    MemoryModelKeyVault,
    OrgKeyStore,
    VaultRefused,
)
from tilo_providers.byok import ProxyRefusal
from tilo_providers.interfaces import GenerateRequest

ORG, OTHER = "org_one", "org_two"


def _key() -> str:
    return "".join(["k", "ey-", secrets.token_hex(16)])


def _ref(**over) -> KeyReference:
    base = {
        "bundle_id": "oa", "auth_mode": "api_key", "project_id": None, "status": "active", "secret_version": 1,
        "set_by": "u_owner", "set_at": "2026-10-13T08:00:00.000Z", "rotated_at": None, "day_cap_credits": 100,
        "fallback_to_tilo": False, "consent_version": 1,
    }  # fmt: skip
    base.update(over)
    return KeyReference(**base)


def test_BK_04_a_rotation_disables_the_earlier_version_and_a_removal_destroys_all() -> None:
    vault = MemoryModelKeyVault()
    assert vault.put(ORG, SLOT, mode="api_key", key=_key(), project_id=None).secret_version == 1
    assert vault.put(ORG, SLOT, mode="api_key", key=_key(), project_id=None).secret_version == 2
    assert vault.versions(ORG) == {1: False, 2: True}
    assert vault.remove(ORG, SLOT) is True and vault.versions(ORG) == {} and vault.status(ORG, SLOT).state == "none"


def test_BK_03_removing_the_new_version_leaves_the_displaced_key_active() -> None:
    vault = MemoryModelKeyVault()
    vault.put(ORG, SLOT, mode="api_key", key=_key(), project_id=None)
    second = vault.put(ORG, SLOT, mode="api_key", key=_key(), project_id=None)
    assert vault.remove(ORG, SLOT, second.secret_version) is True
    assert vault.versions(ORG) == {1: True}


def test_BK_03_a_refused_key_creates_no_version() -> None:
    vault = MemoryModelKeyVault(accepts=lambda _k: False)
    with pytest.raises(VaultRefused) as caught:
        vault.put(ORG, SLOT, mode="api_key", key=_key(), project_id=None)
    assert caught.value.code == "key_refused" and vault.versions(ORG) == {}


def test_BK_03_an_unvalidated_put_is_disabled_so_no_unit_can_use_it() -> None:
    vault = MemoryModelKeyVault(validates=False)
    got = vault.put(ORG, SLOT, mode="api_key", key=_key(), project_id=None)
    assert (got.validated, vault.status(ORG, SLOT).state) == (False, "unverified")
    with pytest.raises(ProxyRefusal) as caught:
        vault.generate(org_id=ORG, slot=SLOT, run_id="r", profile_id="p", request=GenerateRequest(prompt="x"))
    assert caught.value.code == "unverified"


def test_BK_09_the_proxy_answer_is_text_and_usage_only_never_a_key() -> None:
    vault = MemoryModelKeyVault()
    key = _key()
    vault.put(ORG, SLOT, mode="api_key", key=key, project_id=None)
    answer = vault.generate(org_id=ORG, slot=SLOT, run_id="r", profile_id="p", request=GenerateRequest(prompt="x"))
    assert set(answer) <= {"text", "tool_calls", "usage"} and key not in json.dumps(dict(answer))
    with pytest.raises(ProxyRefusal) as caught:  # another org never reaches this org's key
        vault.generate(org_id=OTHER, slot=SLOT, run_id="r", profile_id="p", request=GenerateRequest(prompt="x"))
    assert caught.value.code == "no_key"


def test_BK_04_the_reference_has_no_key_derived_field_and_is_compare_and_set() -> None:
    store = OrgKeyStore()
    ref = _ref()
    assert store.cas(ORG, ref, expected_rev=0) is True
    assert store.cas(ORG, ref.bumped(day_cap_credits=50), expected_rev=0) is False, "a stale writer loses"
    assert store.cas(ORG, ref.bumped(day_cap_credits=50), expected_rev=1) is True
    assert store.get(ORG).day_cap_credits == 50 and store.get(OTHER) is None  # type: ignore[union-attr]
    banned = ("key", "hash", "digest", "last4", "last_four", "fingerprint", "length", "prefix", "suffix")
    assert not [n for n in ref.to_dict() if any(word in n for word in banned)], "BK-04: nothing derived from a key"


def test_BK_08_at_most_five_acts_an_hour_per_org_and_the_window_slides() -> None:
    store = OrgKeyStore()
    for i in range(ACTS_PER_HOUR):
        assert store.note_act(ORG, 1000.0 + i) is None
    wait = store.note_act(ORG, 1010.0)
    assert wait is not None and wait >= 1
    assert store.note_act(OTHER, 1010.0) is None, "another org's count is its own"
    assert store.note_act(ORG, 1000.0 + 3601) is None, "the window slid past the first act"


def test_BK_02_an_audit_entry_is_stored_as_given_and_listed_per_org() -> None:
    store = OrgKeyStore()
    store.audit(ORG, {"id": "a1", "action": "set", "authz": {"tier": "T3"}})
    assert store.audit_entries(ORG)[0]["authz"]["tier"] == "T3" and store.audit_entries(OTHER) == []
