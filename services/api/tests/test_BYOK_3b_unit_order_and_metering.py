"""BYOK-3b (ADR-0041 decisions 6 and 7; BK-14 to BK-17, BQ-BYOK-3, BQ-BYOK-6): the order of a model unit and the org's
own day cap. The table is code; every row is a test. Fakes only: an in-memory vault, a fake model-call source, a fixed
clock, no key (fake secrets are assembled at runtime), no network, no paid call.

The flag is `config/byok.yaml` `enabled`; with it off (the shipped value) `plan_unit` is Tilo's key as before."""

from __future__ import annotations

import ast
import pathlib
import secrets
from datetime import UTC, datetime
from typing import Any

import pytest
import yaml
from tilo_api import byok_unit, deps
from tilo_api.byok_store import SLOT, KeyReference, MemoryModelKeyVault, VaultStatus
from tilo_api.byok_unit import ByokSpend, abort_unit, plan_unit, settle_unit
from tilo_api.spend import InMemorySpendLedger, SpendCaps, SpendGuard
from tilo_metering.flags import InMemoryFlagStore
from tilo_providers.byok import ByokConfig, FakeOrgProviderSource, OrgBundle
from tilo_providers.config import load_providers_config
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router, RouterCredentialError

ORG, OTHER = "org_one", "org_two"
DAY = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
CFG = ByokConfig(
    enabled=True,
    day_cap_credits_max=10_000,
    calls_per_org_per_minute=120,
    consent_version=1,
    bundles={"oa": OrgBundle("oa", "Example", "openai_compat", {"writer": ("org-big", "org-small")})},
)


def _ref(**over: Any) -> KeyReference:
    base: dict[str, Any] = {
        "bundle_id": "oa", "auth_mode": "api_key", "project_id": None, "status": "active", "secret_version": 1,
        "set_by": "u_owner", "set_at": "2026-10-13T08:00:00.000Z", "rotated_at": None, "day_cap_credits": 100,
        "fallback_to_tilo": False, "consent_version": 1,
    }  # fmt: skip
    base.update(over)
    return KeyReference(**base)


def _vault(*orgs: str) -> MemoryModelKeyVault:
    vault = MemoryModelKeyVault()
    for org in orgs:
        vault.put(org, SLOT, mode="api_key", key="".join(["k", "ey-", secrets.token_hex(12)]), project_id=None)
    return vault


def _providers(tmp_path):
    def org(model: str) -> dict[str, Any]:
        return {
            "provider": "openai_compat", "model": model, "context": 100_000, "caps": ["json"],
            "base_url": "https://byok.example.invalid/v1",
        }  # fmt: skip

    def tilo(model: str) -> dict[str, Any]:
        return {"provider": "fake", "model": model, "context": 100_000, "caps": ["json"]}

    models = {
        "example": True,
        "profiles": {
            "tilo-a": tilo("fake-a"), "tilo-b": tilo("fake-b"), "org-big": org("fake-org-big"),
            "org-small": org("fake-org-small"),
        },
        "roles": {"writer": {"primary": "tilo-a", "fallback": "tilo-b"}},
        "rules": {"deny": []},
    }  # fmt: skip
    prices = {
        "status": "set", "effective_date": "2026-10-01", "source": "fake sheet", "currency": "USD",
        "credit_usd": 0.005, "profiles": {p: {"input": 1.0, "output": 2.0} for p in models["profiles"]},
    }  # fmt: skip
    mp, pp = tmp_path / "models.yaml", tmp_path / "prices.yaml"
    mp.write_text(yaml.safe_dump(models), encoding="utf-8")
    pp.write_text(yaml.safe_dump(prices), encoding="utf-8")
    return load_providers_config(mp, pp)


def plan(ref: KeyReference | None = None, vault: Any = None, spend: ByokSpend | None = None, **over: Any):
    kw: dict[str, Any] = {
        "config": CFG, "ref": ref, "vault": vault or _vault(ORG), "spend": spend or ByokSpend(),
        "source": FakeOrgProviderSource(_NO_CONFIG),  # never asked in a plan: the Router asks it
        "org_id": ORG, "run_id": "r_1", "role": "writer", "mode": "live", "demo": False, "personal_scope": False,
        "estimate_credits": 10.0, "now": lambda: DAY,
    }  # fmt: skip
    kw.update(over)
    return plan_unit(**kw)


_NO_CONFIG: Any = None  # plan_unit never calls the source, so the fake needs no providers config here


# --- BK-17: the table of decision 7, row by row ---------------------------------------------------------------------


def test_BK_17_step1_a_demo_session_or_a_non_live_mode_is_replay_and_never_byok() -> None:
    vault = _vault(ORG)
    for kw in ({"demo": True}, {"mode": "replay"}):
        got = plan(_ref(), vault, **kw)
        assert (got.payer, got.uses_tilo_meter, got.blocked, got.binding) == ("tilo", True, False, None)
    assert vault.calls == []


def test_BK_12_flag_off_is_exactly_the_unit_as_before() -> None:
    got = plan(_ref(), config=ByokConfig())
    assert got == byok_unit._TILO and got.binding is None and got.reserved_credits == 0.0  # noqa: SLF001


def test_BK_17_step2_no_key_a_personal_scope_unit_or_an_uncovered_role_use_tilos_key() -> None:
    for kw, ref in (
        ({}, None),  # no key for this org
        ({"personal_scope": True}, _ref()),  # BQ-BYOK-3: personal-scope work never goes to the org key
        ({"role": "director"}, _ref()),  # a role the bundle leaves out stays on Tilo's profile and meter
    ):
        got = plan(ref, **kw)
        assert (got.payer, got.uses_tilo_meter, got.blocked) == ("tilo", True, False), kw


def test_BK_17_step3_an_active_key_runs_the_unit_on_the_org_key_outside_tilos_meter() -> None:
    spend = ByokSpend()
    got = plan(_ref(), spend=spend)
    assert (got.payer, got.uses_tilo_meter, got.blocked) == ("org_key", False, False)
    assert got.binding is not None and (got.binding.org_id, got.binding.slot) == (ORG, SLOT)
    assert got.binding.bundle.id == "oa" and got.reserved_credits == pytest.approx(11.5), "estimate plus 15%"
    assert spend.spent(ORG, "2026-10-13") == pytest.approx(11.5)


@pytest.mark.parametrize(
    "ref_kw, vault_state, code",
    [
        ({"status": "paused"}, "active", "key_paused"),
        ({"status": "invalid"}, "active", "invalid_key"),
        ({"status": "unverified"}, "active", "unverified"),
        ({}, "none", "key_removed"),
        ({}, "unverified", "unverified"),
        ({}, "raises", "unreachable"),
    ],
)
def test_BK_17_step4_a_key_that_cannot_be_used_blocks_the_unit_with_a_fixed_code_and_no_fallback(
    ref_kw: dict[str, Any], vault_state: str, code: str
) -> None:
    vault: Any = _vault(ORG)
    if vault_state == "none":
        vault = MemoryModelKeyVault()
    elif vault_state == "unverified":
        vault.validates = False
        vault.remove(ORG, SLOT)
        vault.put(ORG, SLOT, mode="api_key", key="".join(["k", "ey-", secrets.token_hex(12)]), project_id=None)
    elif vault_state == "raises":
        vault.status = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))  # type: ignore[method-assign]
    spend = ByokSpend()
    got = plan(_ref(**ref_kw), vault, spend)
    assert (got.refused, got.payer, got.uses_tilo_meter, got.binding) == (code, "tilo", False, None)
    assert spend.spent(ORG, "2026-10-13") == 0.0 and vault.calls == [], "no call is made, nothing is reserved"


def test_BK_17_step5_only_the_owners_opt_in_lets_a_blocked_unit_use_tilos_key_with_the_reason() -> None:
    got = plan(_ref(status="invalid", fallback_to_tilo=True))
    assert (got.payer, got.uses_tilo_meter, got.blocked, got.reason) == ("tilo", True, False, "invalid_key")
    off = plan(_ref(status="invalid", fallback_to_tilo=False))
    assert off.blocked and off.reason is None


def test_BK_17_a_revoked_key_blocks_the_unit_at_the_router_too_and_never_falls_back(tmp_path) -> None:
    config = _providers(tmp_path)
    source = FakeOrgProviderSource(config, refuse={"org-big": "invalid_key"})
    binding = byok_unit.OrgBinding(org_id=ORG, slot=SLOT, run_id="r_1", bundle=CFG.bundles["oa"], source=source)
    calls: list[str] = []

    def tilo(profile_id: str) -> Any:
        calls.append(profile_id)
        raise AssertionError("Tilo's key must never be tried for a BYOK unit")

    router = Router(config, provider_for_profile=tilo, live_permitted=True, org=binding)
    with pytest.raises(RouterCredentialError) as caught:
        router.generate("writer", GenerateRequest(prompt="Draft."))
    assert caught.value.code == "invalid_key" and calls == []


# --- BK-14, BK-15: who pays, what counts ----------------------------------------------------------------------------


def test_BK_15_an_org_key_unit_never_touches_the_SEC_16_ledger_but_the_shared_switch_still_stops_it() -> None:
    caps = SpendCaps(
        uid_lifetime_minor=50_000, run_minor=15_000, org_day_minor=None, global_day_hard_minor=500_000,
        unit_reserve_minor=1_000, rate_limit_requests=240, rate_limit_window_s=60,
    )  # fmt: skip
    ledger, flags = InMemorySpendLedger(caps), InMemoryFlagStore()
    guard = SpendGuard(ledger, flags, caps)
    got = plan(_ref())
    assert got.payer == "org_key" and not got.uses_tilo_meter  # the caller does not call guard.begin_unit
    assert ledger.spent_minor("u_x") == 0 and ledger.replay_only() is False
    # a Tilo-metered unit (step 2) does go through the guard
    tilo = plan(None)
    assert tilo.uses_tilo_meter
    assert guard.begin_unit("live", uid="u_x", run_id="r", org_id=ORG, estimate_minor=1000, at=DAY).mode == "live"
    # BQ-BYOK-6: the one replay switch stops the org-key unit too, because the unit's mode arrives as replay
    ledger.trip_replay_only("operator")
    assert guard.replay_only() and plan(_ref(), mode="replay").payer == "tilo"


def test_BK_14_the_plan_says_who_paid_for_the_trace() -> None:
    assert plan(_ref()).payer == "org_key"
    assert plan(None).payer == "tilo"


def test_BK_16_the_day_cap_reserves_estimate_plus_15_percent_and_refuses_at_the_cap_with_no_call() -> None:
    spend, vault = ByokSpend(), _vault(ORG)
    first = plan(_ref(day_cap_credits=100), vault, spend, estimate_credits=80.0)  # 92 reserved
    assert first.payer == "org_key"
    second = plan(_ref(day_cap_credits=100), vault, spend, estimate_credits=10.0)  # 92 + 11.5 > 100
    assert (second.refused, second.payer, second.uses_tilo_meter) == ("cap_reached", "tilo", False)
    assert vault.calls == []
    settle_unit(first, spend, actual_credits=50.0)  # the actual replaces the reservation
    assert spend.spent(ORG, "2026-10-13") == pytest.approx(50.0)
    assert plan(_ref(day_cap_credits=100), vault, spend, estimate_credits=10.0).payer == "org_key"


def test_BK_16_a_cap_refusal_is_not_a_fallback_unless_the_owner_opted_in() -> None:
    spend = ByokSpend()
    assert spend.reserve(ORG, "2026-10-13", 100.0, 100)
    assert plan(_ref(), spend=spend).refused == "cap_reached"
    opted = plan(_ref(fallback_to_tilo=True), spend=spend)
    assert (opted.payer, opted.uses_tilo_meter, opted.reason) == ("tilo", True, "cap_reached")


def test_BK_16_an_aborted_unit_releases_its_reservation_and_the_next_utc_day_starts_clean() -> None:
    spend = ByokSpend()
    got = plan(_ref(), spend=spend)
    abort_unit(got, spend)
    assert spend.spent(ORG, "2026-10-13") == 0.0
    tomorrow = datetime(2026, 10, 14, 0, 1, tzinfo=UTC)
    assert plan(_ref(), spend=spend, now=lambda: tomorrow).day == "2026-10-14"


def test_BK_16_an_overrun_is_committed_in_full() -> None:
    spend = ByokSpend()
    got = plan(_ref(day_cap_credits=100), spend=spend, estimate_credits=10.0)
    settle_unit(got, spend, actual_credits=30.0)
    assert spend.spent(ORG, "2026-10-13") == pytest.approx(30.0)


# --- BQ-BYOK-3 and the other org -----------------------------------------------------------------------------------


def test_BQ_BYOK_3_another_orgs_unit_never_uses_this_orgs_key() -> None:
    vault = _vault(ORG)  # only org one has a key in the vault
    mine = plan(_ref(), vault)
    theirs = plan(None, vault, org_id=OTHER)  # org two has no reference: Tilo's key, as before
    assert mine.binding is not None and mine.binding.org_id == ORG
    assert theirs.binding is None and theirs.payer == "tilo"
    stale = plan(_ref(), vault, org_id=OTHER)  # even with a reference copied across, the vault is asked for OTHER
    assert stale.refused == "key_removed" and vault.calls == []


def test_BK_18_the_plan_is_deterministic_code_it_imports_no_router_no_provider_call_no_model() -> None:
    tree = ast.parse(pathlib.Path(byok_unit.__file__).read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names
    }
    assert not {m for m in imported if m.startswith("tilo_providers") and m != "tilo_providers.byok"}, imported
    assert not {m for m in imported if "harness" in m or "router" in m or "anthropic" in m}, imported


def test_BYOK_deps_router_for_mode_takes_no_org_by_default() -> None:
    import inspect

    assert inspect.signature(deps.router_for_mode).parameters["org"].default is None
    assert VaultStatus("none", None).state == "none"
