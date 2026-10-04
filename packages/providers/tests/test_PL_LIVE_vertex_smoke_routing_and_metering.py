"""PL-02 live Vertex smoke (ticket PL-LIVE-vertex-smoke): routing through config, thinking level, metering.

PRD 6.4 PL-01 (no model id outside config/ and packages/providers), PL-03 (router picks by role), PL-06
(prices from config/prices.yaml, never invented), FR-MTR-01 (credit = US$0.005, price with date and source),
PRD 14.1. Acceptance criteria covered here:

  (3) every call goes through the router and the role-to-profile mapping from config; no model id string in new
      code outside config/ and packages/providers (PL-01);
  (4) thinking level is the minimum the profile allows;
  (5) metering: prices.yaml status "unset" refuses and says exactly which values to confirm (no invented
      numbers); a status-set fixture gives credits = usd / 0.005 per role and in total.

Public interface: `tilo_providers.vertex_smoke` and `scripts/live_vertex_smoke.py` (API_PL_LIVE_vertex_smoke.md).
Fixture prices are conspicuous fakes (`write_prices`), never real prices. No network, see the gate test file.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml
from _vertex_smoke_lib import (
    PROJECT,
    REAL_MODELS,
    REAL_PRICES,
    ROLES,
    SMOKE_SCRIPT,
    SMOKE_SOURCE,
    FakeVertexSdk,
    config_thinking_level,
    env,
    expected_credits,
    invoke_main,
    live_run,
    real_config,
    smoke,
    used_profiles,
    vertex_imports_blocked,
    write_custom_models,
    write_prices,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_providers.config import load_providers_config
from tilo_providers.router import Router

REFUSED_RE = re.compile(r"^REFUSED (?P<code>[a-z_]+): (?P<message>.+)$")
CONFIRM_RE = re.compile(r"^  confirm (?P<key>\S+)$")


# ---------------------------------------------------------------------------------------------------------
# (3) Router and config mapping
# ---------------------------------------------------------------------------------------------------------


def test_PL_LIVE_03_each_role_goes_through_the_router_with_the_capped_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, Any, Any]] = []
    real_generate = Router.generate

    def spy(self: Router, role_id, request, **kwargs):  # type: ignore[no-untyped-def]
        seen.append((role_id, request, kwargs.get("budget")))
        return real_generate(self, role_id, request, **kwargs)

    monkeypatch.setattr(Router, "generate", spy)
    result, sdk, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    assert [role for role, _, _ in seen] == list(ROLES)  # one router call per role, in this order
    module = smoke()
    for _role, request, budget in seen:
        assert request.prompt == module.SMOKE_PROMPT and request.max_output_tokens == 64
        assert budget is not None  # the remaining credit ceiling is enforced by the router's budget (PL-03)
    assert len(sdk.calls) == len(seen)  # no SDK call that did not come from a router call


def test_PL_LIVE_03_profile_and_model_per_role_come_from_the_config_file_given(tmp_path: Path) -> None:
    models, prices, plan = write_custom_models(tmp_path)
    cfg = load_providers_config(models, prices)
    result, sdk, _ = live_run(tmp_path, models=models, prices=prices)
    assert result.code == 0, result.err
    rows = result.rows()
    assert [m["role"] for m in rows] == list(ROLES)
    assert [m["profile"] for m in rows] == [plan[r]["primary"] for r in ROLES]
    assert sdk.models_called() == [cfg.profiles[plan[r]["primary"]].model for r in ROLES]


def test_PL_LIVE_03_real_config_mapping_is_followed(tmp_path: Path) -> None:
    cfg = real_config()
    result, sdk, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    assert [m["profile"] for m in result.rows()] == [cfg.roles[r].primary for r in ROLES]
    assert sdk.models_called() == [cfg.profiles[cfg.roles[r].primary].model for r in ROLES]


def test_PL_LIVE_03_new_code_names_no_model_id_and_no_profile_id() -> None:
    # PL-01: model ids live in config/ and packages/providers only; the role-to-profile mapping lives in config.
    # packages/providers is allowed to hold ids, but the smoke must not hard-wire them either.
    cfg = real_config()
    forbidden = {profile.model for profile in cfg.profiles.values()} | set(cfg.profiles)
    family = re.compile(r"\b(?:gemini|gemma|gpt|claude|llama|mistral|nemotron)-[A-Za-z0-9]")
    for path in (SMOKE_SOURCE, SMOKE_SCRIPT):
        text = path.read_text(encoding="utf-8")
        assert not family.search(text), f"{path.name} names a model family id"
        for name in forbidden:
            assert not re.search(rf"[\"']{re.escape(name)}[\"']", text), f"{path.name} hard-wires {name!r}"


def test_PL_LIVE_03_importing_the_smoke_imports_no_vertex_client() -> None:
    with env(), vertex_imports_blocked() as blocker:
        smoke()
    assert blocker.hits == []


# ---------------------------------------------------------------------------------------------------------
# (4) Thinking level: the minimum, for profiles that think
# ---------------------------------------------------------------------------------------------------------


def test_PL_LIVE_04_thinking_is_minimal_for_every_profile_that_has_the_thinking_capability(tmp_path: Path) -> None:
    cfg = real_config()
    result, sdk, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    assert len(sdk.calls) == 7
    saw_thinking = saw_plain = False
    for role, call in zip(ROLES, sdk.calls, strict=True):
        profile = cfg.profiles[cfg.roles[role].primary]
        level = config_thinking_level(call["config"])
        if "thinking" in profile.caps:
            saw_thinking = True
            # not the role's configured level (director is "high" in config/models.yaml): the minimum
            assert level == "minimal", f"{role}: thinking level {level!r}"
        else:
            saw_plain = True
            assert level is None, f"{role}: profile cannot think, so no thinking config may be sent"
    assert saw_thinking and saw_plain  # the real config exercises both branches


# ---------------------------------------------------------------------------------------------------------
# (5) Metering
# ---------------------------------------------------------------------------------------------------------


def _unset_prices(tmp_path: Path) -> Path:
    """A temporary copy of the prices file in the unset state (no price, date or source). The tests below use it
    instead of config/prices.yaml, whose status changes when the user confirms real prices (ticket PL-06)."""
    raw = yaml.safe_load(REAL_PRICES.read_text(encoding="utf-8"))
    raw.update(status="unset", effective_date=None, source=None)
    raw["profiles"] = {profile_id: {"input": None, "output": None} for profile_id in raw["profiles"]}
    path = tmp_path / "prices.unset.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def test_PL_LIVE_05_unset_prices_refuse_before_any_request_and_list_exactly_what_to_confirm(tmp_path: Path) -> None:
    cfg = real_config()
    unset = _unset_prices(tmp_path)
    assert load_providers_config(REAL_MODELS, unset).prices.status == "unset"
    expected = ["status", "effective_date", "source"]
    for profile_id in used_profiles(cfg):
        expected += [f"{profile_id}.input", f"{profile_id}.output"]
    sdk = FakeVertexSdk()
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), sdk.installed():
        module = smoke()
        with pytest.raises(module.SmokeRefused) as info:
            module.run_vertex_smoke(models_path=REAL_MODELS, prices_path=unset, fixtures_dir=Path("unused"))
        result = invoke_main(["--models-file", str(REAL_MODELS), "--prices-file", str(unset)])
    assert info.value.code == "prices_unset"
    assert list(info.value.missing) == expected
    assert sdk.client_inits == [] and sdk.calls == []  # nothing was sent

    assert result.code == 2
    assert result.out == ""
    lines = result.err_lines()
    head = REFUSED_RE.match(lines[0])
    assert head and head["code"] == "prices_unset" and "config/prices.yaml" in head["message"]
    assert [m["key"] for line in lines[1:] if (m := CONFIRM_RE.match(line))] == expected
    assert len(lines) == 1 + len(expected)  # nothing else printed
    # no invented numbers: none of the researched suggestions in the prices file comments, and no dollar amount
    for number in ("0.75", "3.75", "1.50", "7.50", "0.25"):
        assert number not in result.err
    assert "$" not in result.err


def test_PL_LIVE_05_unset_prices_do_not_touch_the_credential_libraries(tmp_path: Path) -> None:
    unset = _unset_prices(tmp_path)
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), vertex_imports_blocked() as blocker:
        result = invoke_main(["--models-file", str(REAL_MODELS), "--prices-file", str(unset)])
    assert result.code == 2 and blocker.hits == []


def test_PL_LIVE_05_set_prices_give_credits_as_usd_over_0_005_per_role_and_in_total(tmp_path: Path) -> None:
    prices = write_prices(tmp_path)
    cfg = load_providers_config(REAL_MODELS, prices)
    assert cfg.prices.credit_usd == 0.005
    result, sdk, _ = live_run(tmp_path, prices=prices, sdk=FakeVertexSdk(usage=(20, 30), delay_s=0.02))
    assert result.code == 0, result.err
    assert result.err == ""
    rows = result.rows()
    assert [m["role"] for m in rows] == list(ROLES)
    total = 0.0
    for match in rows:
        want = expected_credits(cfg, match["profile"], 20, 30)
        assert (int(match["tin"]), int(match["tout"])) == (20, 30)
        assert float(match["credits"]) == pytest.approx(want, abs=1e-4)
        assert float(match["latency"]) >= 15  # the fake SDK takes 20 ms; latency is the call's wall time in ms
        assert match["fallback_from"] is None
        total += want
    printed_total = result.total()
    assert printed_total is not None
    assert float(printed_total["credits"]) == pytest.approx(total, abs=2e-4)
    assert float(printed_total["ceiling"]) == pytest.approx(50.0, abs=1e-4)
    assert len(sdk.calls) == 7


def test_PL_LIVE_05_run_vertex_smoke_returns_the_same_numbers_as_it_prints(tmp_path: Path) -> None:
    prices = write_prices(tmp_path)
    cfg = load_providers_config(REAL_MODELS, prices)
    sdk = FakeVertexSdk(usage=(20, 30))
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), sdk.installed():
        module = smoke()
        report = module.run_vertex_smoke(
            models_path=REAL_MODELS, prices_path=prices, fixtures_dir=tmp_path / "f", max_total_credits=50.0
        )
    assert [row.role for row in report.rows] == list(ROLES)
    for row in report.rows:
        assert (row.tokens_in, row.tokens_out) == (20, 30)
        assert row.credits == pytest.approx(expected_credits(cfg, row.profile_id, 20, 30), rel=1e-9)
        assert row.latency_ms >= 0 and row.fallback_from is None
    assert report.total_credits == pytest.approx(sum(r.credits for r in report.rows), rel=1e-9)
    assert report.ceiling_credits == 50.0


def test_PL_LIVE_05_usd_is_never_computed_from_a_hard_coded_price() -> None:
    # prices come from the prices file only (PL-06): with prices doubled, credits double
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        one = write_prices(tmp, scale=1.0, name="one.yaml")
        two = write_prices(tmp, scale=2.0, name="two.yaml")
        results = []
        for prices in (one, two):
            sdk = FakeVertexSdk(usage=(20, 30))
            with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), sdk.installed():
                module = smoke()
                results.append(
                    module.run_vertex_smoke(
                        models_path=REAL_MODELS, prices_path=prices, fixtures_dir=tmp / "f", max_total_credits=50.0
                    )
                )
    assert results[1].total_credits == pytest.approx(2 * results[0].total_credits, rel=1e-9)


def test_PL_LIVE_05_the_smoke_never_edits_the_prices_file(tmp_path: Path) -> None:
    # a temporary set copy (a full run) and a temporary unset copy (a refusal): bytes and mtime unchanged by both
    paths = [write_prices(tmp_path), _unset_prices(tmp_path)]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    for prices in paths:
        live_run(tmp_path, prices=prices)
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


# ---------------------------------------------------------------------------------------------------------
# Property: the ceiling is never exceeded, and a call is never made that the ceiling cannot cover
# ---------------------------------------------------------------------------------------------------------


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ceiling=st.floats(min_value=0.05, max_value=8.0, allow_nan=False, allow_infinity=False))
def test_PL_LIVE_02_property_total_spend_never_exceeds_the_ceiling(ceiling: float) -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        # uniform fixture prices: 50 in / 100 out per million; a call really costs 0.8 credits, may cost 1.28+
        prices = write_prices(tmp, uniform=(50.0, 100.0))
        sdk = FakeVertexSdk(usage=(20, 30))
        outcome = None
        with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), sdk.installed():
            module = smoke()
            try:
                report = module.run_vertex_smoke(
                    models_path=REAL_MODELS, prices_path=prices, fixtures_dir=tmp / "f", max_total_credits=ceiling
                )
                outcome = ("ok", report)
            except module.SmokeFailed as failure:
                outcome = ("failed", failure.report)
                assert failure.code == "ceiling"
    kind, report = outcome
    assert report.total_credits <= ceiling + 1e-9
    assert len(sdk.calls) == len(report.rows) <= 7  # every request made is a row; none beyond the ceiling
    if kind == "ok":
        assert len(report.rows) == 7
    else:
        assert len(report.rows) < 7
