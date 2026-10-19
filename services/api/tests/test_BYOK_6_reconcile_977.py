"""BYOK-6 (ADR-0041, BQ-BYOKC-5 and BQ-BYOKC-6): `/v1/org/model-key` answers and writes what
contracts/org_model_key.schema.json says. INERT: nothing here turns `config/byok.yaml` on.

Every body is judged by the JSON Schema itself (the generated pydantic models do not enforce `if/then/else`,
`dependentRequired` or `not`): the answers, the audit entries and each fixture of `put_request` and `patch_request`.
Fake keys are assembled at runtime; no network, no cloud, no paid call."""

from __future__ import annotations

import functools
import json
import pathlib
from dataclasses import replace
from typing import Any

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from test_BYOK_3a_org_model_key_routes import MEMBER, NOW, ORG, OWNER, PATH, Rig, fake_key
from tilo_api import app, byok_routes
from tilo_api.byok_store import MemoryModelKeyVault, VaultRefused
from tilo_providers.byok import ByokConfig, OrgBundle

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
HOST = "https://contracts.tilo.example/"
BUNDLE = "openai-compat-example"  # the id the contract's fixtures use
CFG = ByokConfig(
    enabled=True,
    day_cap_credits_max=10_000,
    calls_per_org_per_minute=120,
    consent_version=1,
    bundles={
        BUNDLE: OrgBundle(BUNDLE, "OpenAI-compatible endpoint (example)", "openai_compat", {"writer": ("a", "b")})
    },
)


@functools.cache
def _registry() -> Registry:
    found = []
    for path in sorted(CONTRACTS.glob("*.schema.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        found.append((doc["$id"], Resource.from_contents(doc, default_specification=DRAFT202012)))
    return Registry().with_resources(found)


def verdict(name: str, doc: Any) -> list[str]:
    """Errors of `doc` against `org_model_key.schema.json#/$defs/<name>` (empty: valid)."""
    check = jsonschema.Draft202012Validator(
        {"$ref": f"{HOST}org_model_key.schema.json#/$defs/{name}"}, registry=_registry()
    )
    return [e.message[:200] for e in check.iter_errors(doc)]


def fixtures(name: str, kind: str) -> list[Any]:
    root = CONTRACTS / "fixtures" / f"org_model_key.{name}" / kind
    return [pytest.param(json.loads(p.read_text("utf-8")), id=p.stem) for p in sorted(root.glob("*.json"))]


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(monkeypatch, config=CFG)


def put(rig: Rig, **over: Any) -> Any:
    """A valid set under this file's config (consent version 1, the fixtures' bundle); `None` leaves a field out."""
    body = {"confirm": True, "consent_version": 1, "bundle_id": BUNDLE, "day_cap_credits": 500, "key": fake_key()}
    body.update(over)
    return rig.client.put(PATH, json={k: v for k, v in body.items() if v is not None})


# --- BQ-BYOKC-6: 403 `owner_only`, never `forbidden`; every refusal is the contract's `error` ------------------------


def test_BYOK_6_a_principal_with_no_directory_record_is_owner_only_not_forbidden(rig: Rig) -> None:
    rig.user = "u_unknown"
    for got in (
        rig.client.get(PATH),
        put(rig),
        rig.client.patch(PATH, json={"paused": True}),
        rig.client.delete(PATH),
    ):
        assert (got.status_code, got.json()) == (403, {"detail": "owner_only"})
    assert rig.vault.versions(ORG) == {} and rig.store.get(ORG) is None


def test_BYOK_6_every_refusal_body_is_the_contracts_error(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch, config=CFG)
    seen: dict[str, int] = {}

    def refused(got: Any, status: int, word: str) -> None:
        assert got.status_code == status and got.json()["detail"] == word, got.text
        assert verdict("error", got.json()) == [], got.json()
        seen[word] = got.status_code

    rig.user = MEMBER
    refused(put(rig), 403, "owner_only")
    rig.user, rig.demo = OWNER, True
    refused(put(rig), 403, "owner_only")
    rig.demo, rig.age = False, 601.0
    refused(put(rig), 401, "reauth_required")
    rig.age = 120.0
    refused(put(rig, confirm=False), 422, "confirm_required")
    refused(put(rig, key="short"), 422, "key_refused")
    refused(put(rig, surprise=1), 422, "invalid_body")
    refused(put(rig, day_cap_credits=10_001), 422, "invalid_body")
    rig.vault.put = lambda *a, **k: (_ for _ in ()).throw(VaultRefused("unavailable"))  # type: ignore[method-assign]
    refused(put(rig), 503, "unavailable")
    rig.vault = MemoryModelKeyVault()  # the override reads `rig.vault` on every call
    for _ in range(4):
        assert put(rig).status_code == 200  # with the act above, five widening acts an hour (BK-08)
    refused(put(rig), 429, "rate_limited")
    app.dependency_overrides[byok_routes.get_byok_config] = lambda: ByokConfig()
    refused(rig.client.get(PATH), 503, "not_configured")
    assert set(seen) == {
        "owner_only", "reauth_required", "confirm_required", "key_refused", "invalid_body", "unavailable",
        "rate_limited", "not_configured",
    }  # fmt: skip


# --- BQ-BYOKC-5c: the audit entry's authz is the common authz --------------------------------------------------------


def test_BYOK_6_audit_authz_is_the_common_person_authz_and_every_entry_matches_the_schema(rig: Rig) -> None:
    assert put(rig).status_code == 200  # set
    assert put(rig).status_code == 200  # rotate
    assert rig.client.patch(PATH, json={"paused": True}).status_code == 200  # a narrowing act
    resume = {"paused": False, "confirm": True, "consent_version": 1}
    assert rig.client.patch(PATH, json=resume).status_code == 200  # a widening act
    assert rig.client.delete(PATH).status_code == 200
    entries = rig.store.audit_entries(ORG)
    assert [e["action"] for e in entries] == ["set", "rotate", "change", "change", "remove"]
    for entry in entries:
        assert verdict("audit_entry", entry) == [], entry
        assert entry["authz"] == {"by": "person", "ref": OWNER, "at": NOW}
        assert (entry["authz"]["ref"], entry["authz"]["at"]) == (entry["actor"], entry["at"])
    assert (entries[-1]["bundle"], entries[-1]["version"]) == (None, None), "after a removal there is no reference"
    assert [(e["bundle"], e["version"]) for e in entries[:2]] == [(BUNDLE, 1), (BUNDLE, 2)]


# --- BQ-BYOKC-5d and BQ-BYOKC-6: the owner's view -------------------------------------------------------------------


def test_BYOK_6_owner_view_consent_version_is_the_configs_current_one_not_the_stored_one(rig: Rig) -> None:
    assert rig.client.get(PATH).json()["consent_version"] == 1
    assert put(rig).status_code == 200  # stored consent_version 1
    app.dependency_overrides[byok_routes.get_byok_config] = lambda: replace(CFG, consent_version=4)
    got = rig.client.get(PATH).json()
    assert got["consent_version"] == 4 and verdict("owner_view", got) == []
    assert rig.client.patch(PATH, json={"paused": True}).json()["consent_version"] == 4  # the PATCH answer too


def test_BYOK_6_no_answer_carries_auth_mode_or_project_id(rig: Rig) -> None:
    put(rig)
    owner = rig.client.get(PATH).json()
    assert not {"auth_mode", "project_id"} & set(owner) and verdict("owner_view", owner) == []
    patched = rig.client.patch(PATH, json={"day_cap_credits": 100}).json()
    assert not {"auth_mode", "project_id"} & set(patched) and verdict("owner_view", patched) == []


def test_BYOK_6_every_state_answer_matches_its_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch, config=CFG)
    none = rig.client.get(PATH).json()
    assert none["state"] == "none" and verdict("owner_view", none) == []
    rig.vault.validates = False  # the process may not go live (EFF-01): stored, never validated
    stored = put(rig).json()
    assert stored["state"] == "unverified" and verdict("put_answer", stored) == []
    unverified = rig.client.get(PATH).json()
    assert unverified["state"] == "unverified" and unverified["active"] is False
    assert verdict("owner_view", unverified) == []
    rig.vault.validates = True
    active = put(rig).json()
    assert active["state"] == "active" and verdict("put_answer", active) == []
    owner = rig.client.get(PATH).json()
    assert owner["active"] is True and verdict("owner_view", owner) == []
    paused = rig.client.patch(PATH, json={"paused": True}).json()
    assert paused["state"] == "paused" and paused["active"] is False and verdict("owner_view", paused) == []
    held = rig.store.get(ORG)
    assert held is not None
    rig.store.cas(ORG, held.bumped(status="invalid", refusals=3, last_error="invalid_key"), expected_rev=held.rev)
    invalid = rig.client.get(PATH).json()
    assert invalid["state"] == "invalid" and invalid["last_error"] == "invalid_key"
    assert verdict("owner_view", invalid) == []
    rig.user = MEMBER
    member = rig.client.get(PATH).json()
    assert member == {"active": False, "label": CFG.bundles[BUNDLE].label} and verdict("member_view", member) == []
    rig.user = OWNER
    removed = rig.client.delete(PATH).json()
    assert removed == {"removed": True} and verdict("remove_answer", removed) == []


def test_BYOK_6_owner_view_of_a_key_whose_bundle_left_the_config_matches_the_schema(rig: Rig) -> None:
    put(rig)
    gone = replace(CFG, bundles={"other": OrgBundle("other", "Other", "openai_compat", {"writer": ("a", "b")})})
    app.dependency_overrides[byok_routes.get_byok_config] = lambda: gone
    got = rig.client.get(PATH).json()
    assert got["active"] is False and got["last_error"] == "not_configured"  # B4 stays as built
    assert verdict("owner_view", got) == []


# --- the contract's own fixtures are the request oracle --------------------------------------------------------------


@pytest.mark.parametrize("body", fixtures("put_request", "invalid"))
def test_BYOK_6_put_refuses_every_invalid_put_request_fixture(rig: Rig, body: Any) -> None:
    got = rig.client.put(PATH, json=body)
    assert got.status_code == 422 and verdict("error", got.json()) == [], got.text
    key = body.get("key") if isinstance(body, dict) else None
    assert not isinstance(key, str) or len(key) < 8 or key not in got.text, "a refused body never echoes its input"
    assert rig.vault.versions(ORG) == {} and rig.store.get(ORG) is None and rig.store.audit_entries(ORG) == []


@pytest.mark.parametrize("body", fixtures("put_request", "valid"))
def test_BYOK_6_put_accepts_every_valid_put_request_fixture(rig: Rig, body: Any) -> None:
    assert verdict("put_request", body) == []
    got = rig.client.put(PATH, json=body)
    assert got.status_code == 200 and verdict("put_answer", got.json()) == [], got.text
    assert rig.store.get(ORG).fallback_to_tilo is body.get("fallback_to_tilo", False)  # type: ignore[union-attr]


def _active(rig: Rig) -> None:
    assert put(rig, key=fake_key(), day_cap_credits=500).status_code == 200


@pytest.mark.parametrize("body", fixtures("patch_request", "invalid"))
def test_BYOK_6_patch_refuses_every_invalid_patch_request_fixture_and_changes_nothing(rig: Rig, body: Any) -> None:
    _active(rig)
    before = rig.store.get(ORG)
    got = rig.client.patch(PATH, json=body)
    assert got.status_code == 422 and verdict("error", got.json()) == [], got.text
    assert rig.store.get(ORG) == before and len(rig.store.audit_entries(ORG)) == 1


@pytest.mark.parametrize("body", fixtures("patch_request", "valid"))
def test_BYOK_6_patch_accepts_every_valid_patch_request_fixture(rig: Rig, body: Any) -> None:
    _active(rig)
    got = rig.client.patch(PATH, json=body)
    assert got.status_code == 200 and verdict("owner_view", got.json()) == [], got.text
