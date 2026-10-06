"""FR-MTR-10 (Should): "Cost dashboards by task type and model profile". Acceptance (PRD 14.5): "Dashboard shows cost
per task by tier and profile". This is the data half: `tilo_metering.costs.cost_report`, a pure function over the
Treasury ledger and recorded events. No UI, no route (see services/api/tests/API_FR_MTR_10.md for those).

Sources: PRD 14.1 (credit unit, ledger), 14.3 and FR-MTR-06 (credits saved), 14.4 ("Cost per task: ledger `runs` table
x US$0.005"), 3.5 EV-07 ("Credits per successful run, by tier, with USD"), FR-MTR-01 (price in effect on the entry's
date), PL-01 (no model id outside config/ and providers), `contracts/metering.rules.md`.

Pinned interface (the builder may override it; update the tests with it):

    cost_report(ledger, events, *, unit_types, credit_usd) -> dict
        ledger      iterable of tilo_metering.LedgerEntry (Treasury.ledger); only `commit` entries are spend
        events      iterable of event.schema.json records (any worlds): world.planned (tier), world.completed,
                    memory.hit (saved credits); everything else is ignored
        unit_types  {run_id: {plan unit id: unit_type}}; a ledger entry's `step` is read as the plan unit id
    "tier" is the world tier of PRD 9.1 (outpost, village, town, city; world.planned data.tier), as in PRD 14.5 and
    EV-07, not the T1-T3 risk tier. A task is a run.

These fail today with ModuleNotFoundError: tilo_metering.costs does not exist yet. No network, no provider.
"""

from __future__ import annotations

import copy
import json
import math
import random

import pytest
from _costs_lib import (
    CREDIT_USD,
    FLASH,
    H1,
    LITE,
    UNIT_TYPES,
    at,
    build_ledger,
    commits,
    completed,
    event,
    hit,
    model_ids,
    planned,
    price_book,
    row,
    scenario_events,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_metering import LedgerEntry, Usage
from tilo_metering.costs import cost_report
from tilo_metering.savings import InconsistentMemoryHit

settings.register_profile("costs", deadline=None, max_examples=60)
settings.load_profile("costs")


def report(tmp_path, *, noise: bool = False, hits: bool = True) -> dict:
    ledger = build_ledger(tmp_path, noise=noise).ledger
    return cost_report(ledger, scenario_events(hits=hits), unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)


def near(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)


# --- FR-MTR-01: sums match the ledger, at the price in effect on each entry's date ------------------------------


def test_FR_MTR_10_FR_MTR_01_totals_equal_the_ledger_exactly(tmp_path):
    t = build_ledger(tmp_path)
    ledger = t.ledger
    out = cost_report(ledger, scenario_events(), unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert out["totals"]["credits"] == math.fsum(e.credits for e in commits(ledger))  # exact, not approximate
    assert near(out["totals"]["credits"], 322)
    assert out["credit_usd"] == CREDIT_USD
    assert near(out["totals"]["usd"], 322 * CREDIT_USD)


def test_FR_MTR_10_FR_MTR_01_each_entry_keeps_the_price_in_effect_on_its_date(tmp_path):
    """The same 100k-in/50k-out call cost 40 credits under sheet v1 and 120 under v2; the report must not re-price
    the old call at today's sheet (nor the new one at the old sheet)."""
    t = build_ledger(tmp_path)
    flash = sorted((e for e in commits(t.ledger) if e.usage and e.usage.profile == FLASH), key=lambda e: e.at)
    assert [e.price_effective_date for e in flash] == ["2026-01-01", "2026-01-01", "2026-06-01"]  # r_a3, r_a1, r_a1
    assert [round(e.credits) for e in flash] == [40, 40, 120]
    today = price_book(tmp_path).credits(Usage(FLASH, 100_000, 50_000), at("2026-10-06"))
    assert round(today) == 120  # re-pricing every flash call at today's sheet would give 360, not 200
    out = cost_report(t.ledger, scenario_events(), unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    flash_row = row(out["by_profile"], profile=FLASH)
    assert near(flash_row["credits"], 200)
    assert flash_row["credits"] == math.fsum(e.credits for e in flash)
    assert near(row(out["by_profile"], profile=LITE)["credits"], 120)
    assert near(row(out["by_profile"], profile=None)["credits"], 2)  # the plain commit carries no usage, so no profile


def test_FR_MTR_10_only_commits_are_spend(tmp_path):
    """A released reservation, a grant and usage records (priced or not) are in the ledger but are not cost."""
    quiet = report(tmp_path)
    noisy_ledger = build_ledger(tmp_path, noise=True).ledger
    assert {e.kind for e in noisy_ledger} >= {"commit", "release", "grant", "usage"}  # the noise is really there
    noisy = cost_report(noisy_ledger, scenario_events(), unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert noisy == quiet
    assert near(noisy["totals"]["credits"], 322)


# --- the grouping: task, tier, profile, task type ---------------------------------------------------------------


def test_FR_MTR_10_cost_per_task_by_tier_and_profile(tmp_path):
    """The acceptance line: one row per (tier, profile) with its tasks, credits, US$ and credits per task."""
    out = report(tmp_path)
    rows = out["by_tier_profile"]
    assert len(rows) == 5
    expected = {  # (tier, profile): (tasks, credits)
        ("outpost", LITE): (1, 40),
        ("outpost", None): (1, 2),
        ("village", FLASH): (1, 160),
        ("village", LITE): (2, 80),
        (None, FLASH): (1, 40),  # r_a3 was never planned, so it has no tier
    }
    for (tier, profile), (tasks, credits) in expected.items():
        r = row(rows, tier=tier, profile=profile)
        assert r["tasks"] == tasks
        assert near(r["credits"], credits)
        assert near(r["usd"], credits * CREDIT_USD)
        assert near(r["credits_per_task"], credits / tasks)


def test_FR_MTR_10_cost_per_task_by_tier(tmp_path):
    out = report(tmp_path)
    assert len(out["by_tier"]) == 3
    village = row(out["by_tier"], tier="village")  # r_a1 (200) and r_a4 (40)
    assert village["tasks"] == 2
    assert near(village["credits"], 240)
    assert near(village["credits_per_task"], 120)
    assert near(village["usd"], 240 * CREDIT_USD)
    outpost = row(out["by_tier"], tier="outpost")
    assert (outpost["tasks"], round(outpost["credits"]), round(outpost["credits_per_task"])) == (1, 42, 42)
    unplanned = row(out["by_tier"], tier=None)
    assert (unplanned["tasks"], round(unplanned["credits"])) == (1, 40)


def test_FR_MTR_10_cost_by_model_profile(tmp_path):
    out = report(tmp_path)
    assert len(out["by_profile"]) == 3
    flash, lite, none = (row(out["by_profile"], profile=p) for p in (FLASH, LITE, None))
    assert (flash["tasks"], near(flash["credits"], 200), near(flash["credits_per_task"], 100)) == (2, True, True)
    assert (lite["tasks"], near(lite["credits"], 120), near(lite["credits_per_task"], 40)) == (3, True, True)
    assert (none["tasks"], near(none["credits"], 2)) == (1, True)
    assert near(flash["usd"], 200 * CREDIT_USD)


def test_FR_MTR_10_cost_by_task_type_reads_the_plan_unit_of_each_step(tmp_path):
    """`step` is the plan unit id; its unit_type (plan.schema.json) is the task type. A step the plan does not list
    (r_a2's U9) is reported under task_type null, never dropped, so the sums still equal the ledger."""
    out = report(tmp_path)
    assert len(out["by_task_type"]) == 3
    research = row(out["by_task_type"], task_type="research")  # r_a1 U1+U3, r_a2 U1, r_a4 U1
    assert (research["tasks"], near(research["credits"], 160)) == (3, True)
    draft = row(out["by_task_type"], task_type="draft")  # r_a1 U2 (120), r_a3 U1 (40)
    assert (draft["tasks"], near(draft["credits"], 160), near(draft["credits_per_task"], 80)) == (2, True, True)
    other = row(out["by_task_type"], task_type=None)
    assert (other["tasks"], near(other["credits"], 2)) == (1, True)


def test_FR_MTR_10_each_task_is_one_run_with_its_tier_and_state(tmp_path):
    out = report(tmp_path)
    assert [t["run_id"] for t in out["tasks"]] == ["r_a1", "r_a2", "r_a3", "r_a4"]
    by_run = {t["run_id"]: t for t in out["tasks"]}
    assert (by_run["r_a1"]["tier"], by_run["r_a1"]["completed"], round(by_run["r_a1"]["credits"])) == (
        "village",
        True,
        200,
    )
    assert (by_run["r_a2"]["tier"], by_run["r_a2"]["completed"], round(by_run["r_a2"]["credits"])) == (
        "outpost",
        True,
        42,
    )
    assert (by_run["r_a3"]["tier"], by_run["r_a3"]["completed"], round(by_run["r_a3"]["credits"])) == (None, False, 40)
    assert (by_run["r_a4"]["tier"], by_run["r_a4"]["completed"], round(by_run["r_a4"]["credits"])) == (
        "village",
        True,
        40,
    )
    assert near(by_run["r_a1"]["usd"], 200 * CREDIT_USD)
    assert (out["totals"]["tasks"], out["totals"]["completed_tasks"]) == (
        4,
        3,
    )  # an unfinished run is a task, not "done"


def test_FR_MTR_10_every_grouping_adds_up_to_the_ledger(tmp_path):
    out = report(tmp_path)
    total = out["totals"]["credits"]
    for key in ("tasks", "by_tier", "by_profile", "by_task_type", "by_tier_profile"):
        assert near(math.fsum(r["credits"] for r in out[key]), total), key
    assert near(math.fsum(r["usd"] for r in out["by_profile"]), out["totals"]["usd"])


# --- empty data: zeros, not errors ------------------------------------------------------------------------------


def test_FR_MTR_10_nothing_recorded_is_zeros_not_an_error():
    out = cost_report([], [], unit_types={}, credit_usd=CREDIT_USD)
    assert out["credit_usd"] == CREDIT_USD
    assert out["totals"] == {
        "tasks": 0,
        "completed_tasks": 0,
        "credits": 0,
        "usd": 0,
        "credits_saved": 0,
        "usd_saved": 0,
    }
    for key in ("tasks", "by_tier", "by_profile", "by_task_type", "by_tier_profile"):
        assert out[key] == [], key
    cost_report(iter([]), iter([]), unit_types={}, credit_usd=CREDIT_USD)  # plain iterators are fine too


def test_FR_MTR_10_a_run_with_events_but_no_spend_costs_zero_and_never_divides_by_zero():
    out = cost_report([], [planned("r_a1", "village", 1), completed("r_a1", 2)], unit_types={}, credit_usd=CREDIT_USD)
    assert [(t["run_id"], t["tier"], t["completed"], t["credits"]) for t in out["tasks"]] == [
        ("r_a1", "village", True, 0)
    ]
    village = row(out["by_tier"], tier="village")
    assert (village["tasks"], village["credits"], village["credits_per_task"]) == (1, 0, 0)
    assert out["by_profile"] == [] and out["by_task_type"] == [] and out["by_tier_profile"] == []


def test_FR_MTR_10_a_run_with_spend_but_no_events_is_reported_untiered(tmp_path):
    ledger = build_ledger(tmp_path).ledger
    out = cost_report(ledger, [], unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert [t["tier"] for t in out["tasks"]] == [None] * 4
    assert (out["totals"]["completed_tasks"], near(out["totals"]["credits"], 322)) == (0, True)
    assert near(row(out["by_tier"], tier=None)["credits"], 322)


def test_FR_MTR_10_an_unpriced_usage_record_counts_zero_credits_and_does_not_raise(tmp_path):
    """Treasury.record_usage keeps tokens with credits None when a price is unset; cost never guesses one."""
    ledger = list(build_ledger(tmp_path).ledger)
    ledger.append(
        LedgerEntry("usage", "r_a1", "u_owner", "org_test", at("2026-06-06"), usage=Usage(FLASH, 10**6, 10**6))
    )
    out = cost_report(ledger, scenario_events(), unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert near(out["totals"]["credits"], 322)


# --- FR-MTR-06: credits saved, counted once ---------------------------------------------------------------------


def test_FR_MTR_10_FR_MTR_06_saved_credits_are_origin_minus_lookup_per_hit_and_per_task(tmp_path):
    out = report(tmp_path)
    saved = {t["run_id"]: t["credits_saved"] for t in out["tasks"]}
    assert near(saved["r_a1"], 6 - 0.5)
    assert near(saved["r_a4"], 10 - 1)
    assert saved["r_a2"] == 0 and saved["r_a3"] == 0
    assert near(out["totals"]["credits_saved"], 14.5)
    assert near(out["totals"]["usd_saved"], 14.5 * CREDIT_USD)
    assert near(row(out["by_tier"], tier="village")["credits_saved"], 14.5)
    assert row(out["by_tier"], tier="outpost")["credits_saved"] == 0


def test_FR_MTR_10_FR_MTR_06_a_redelivered_hit_is_counted_once(tmp_path):
    events = scenario_events()
    assert sum(1 for e in events if e["id"] == H1["id"]) == 2  # the scenario delivers H1 twice
    out = cost_report(build_ledger(tmp_path).ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert near(out["totals"]["credits_saved"], 14.5)  # not 20
    doubled = cost_report(build_ledger(tmp_path).ledger, events * 2, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert near(doubled["totals"]["credits_saved"], 14.5)


def test_FR_MTR_10_FR_MTR_06_savings_are_not_netted_off_spend_and_not_counted_as_spend(tmp_path):
    """Spend comes from the ledger alone. A hit neither lowers it by `saved` nor adds its own `credits` (the lookup,
    already a ledger commit) a second time."""
    without = report(tmp_path, hits=False)
    events = scenario_events()
    for e in events:
        if e["type"] == "memory.hit":
            e["credits"] = e["data"]["lookup_cost"]  # the event carries its lookup cost, as a metering event may
    with_hits = cost_report(build_ledger(tmp_path).ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert without["totals"]["credits_saved"] == 0
    for key in ("tasks", "by_tier", "by_profile", "by_task_type", "by_tier_profile"):
        spend_without = [{k: v for k, v in r.items() if k != "credits_saved"} for r in without[key]]
        spend_with = [{k: v for k, v in r.items() if k != "credits_saved"} for r in with_hits[key]]
        assert spend_with == spend_without, key
    assert near(with_hits["totals"]["credits"], 322)


def test_FR_MTR_10_FR_MTR_06_only_memory_hit_events_count_as_saved(tmp_path):
    impostor = event("memory.saved", run="r_a1", seq=60, data={"layer": "result_cache", "item_count": 3, "saved": 99})
    out = cost_report(
        build_ledger(tmp_path).ledger, scenario_events() + [impostor], unit_types=UNIT_TYPES, credit_usd=CREDIT_USD
    )
    assert near(out["totals"]["credits_saved"], 14.5)


def test_FR_MTR_10_FR_MTR_06_a_hit_that_disagrees_with_its_own_costs_is_refused_like_the_meter_does(tmp_path):
    bad = hit("r_a1", 61, 6, 0.5)
    bad["data"]["saved"] = 6  # EV-09: saved must be origin_cost - lookup_cost
    with pytest.raises(InconsistentMemoryHit):
        cost_report(
            build_ledger(tmp_path).ledger, scenario_events() + [bad], unit_types=UNIT_TYPES, credit_usd=CREDIT_USD
        )


# --- deterministic ordering -------------------------------------------------------------------------------------


def test_FR_MTR_10_rows_come_in_a_fixed_order(tmp_path):
    """Tiers by world size (PRD 9.1) then null; profiles and task types alphabetically then null; tasks by run id."""
    out = report(tmp_path)
    assert [r["tier"] for r in out["by_tier"]] == ["outpost", "village", None]
    assert [r["profile"] for r in out["by_profile"]] == [FLASH, LITE, None]
    assert [r["task_type"] for r in out["by_task_type"]] == ["draft", "research", None]
    assert [(r["tier"], r["profile"]) for r in out["by_tier_profile"]] == [
        ("outpost", LITE),
        ("outpost", None),
        ("village", FLASH),
        ("village", LITE),
        (None, FLASH),
    ]


def test_FR_MTR_10_tier_order_follows_world_size_even_with_all_four_tiers():
    events = [planned(f"r_{tier}", tier, i) for i, tier in enumerate(["city", "outpost", "town", "village"], 1)]
    assert [r["tier"] for r in cost_report([], events, unit_types={}, credit_usd=CREDIT_USD)["by_tier"]] == [
        "outpost",
        "village",
        "town",
        "city",
    ]


def test_FR_MTR_10_the_same_inputs_in_any_order_give_the_same_report(tmp_path):
    ledger = list(build_ledger(tmp_path).ledger)
    events = scenario_events()
    expected = cost_report(ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    for seed in range(5):
        rng = random.Random(seed)
        rng.shuffle(ledger)
        rng.shuffle(events)
        assert cost_report(ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD) == expected
        assert json.dumps(cost_report(ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)) == json.dumps(
            expected
        )


def test_FR_MTR_10_the_report_is_json_with_no_nan_and_leaves_its_inputs_alone(tmp_path):
    ledger = tuple(build_ledger(tmp_path).ledger)
    events = scenario_events()
    before = copy.deepcopy(events)
    out = cost_report(ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    json.dumps(out, allow_nan=False)
    assert events == before
    assert (
        cost_report(ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD) == out
    )  # a second call changes nothing


# --- PL-01: profiles only, never a model id ---------------------------------------------------------------------


def test_FR_MTR_10_PL_01_the_report_names_profiles_and_never_a_model_id(tmp_path):
    ids = model_ids()
    assert ids, "config/models*.yaml should list model ids; the check below would be vacuous without them"
    ledger = list(build_ledger(tmp_path).ledger)
    hostile = sorted(ids)[0]
    ledger = [
        LedgerEntry(**{**e.__dict__, "price_source": f"Fake sheet for {hostile}"}) if e.kind == "commit" else e
        for e in ledger
    ]
    events = scenario_events()
    for e in events:
        e["summary"] = f"{hostile} said hello"
        e["trace"]["model_role"] = "specialist"
    text = json.dumps(cost_report(ledger, events, unit_types=UNIT_TYPES, credit_usd=CREDIT_USD))
    for model in ids:
        assert model not in text, f"model id {model!r} leaked into the cost report"
    assert f'"{FLASH}"' in text and f'"{LITE}"' in text


def test_FR_MTR_10_PL_01_a_model_id_recorded_as_a_profile_is_hidden_and_still_counted(tmp_path):
    """providers.schema.json profile_id is ^[a-z][a-z0-9-]{0,31}$. A usage whose `profile` is not one (a model id
    written by mistake) is reported under profile null: its credits stay in every sum, its text never appears."""
    ids = sorted(i for i in model_ids() if "." in i or "/" in i)
    assert ids, "config/models*.yaml should list a model id that is not a profile id"
    t = build_ledger(tmp_path)
    bad = LedgerEntry(
        "commit", "r_a1", "u_owner", "org_test", at("2026-06-07"), "U1", 8.0,
        usage=Usage(ids[0], 1, 1), price_effective_date="2026-06-01", price_source="Fake price sheet v2 for tests.",
    )  # fmt: skip
    out = cost_report([*t.ledger, bad], scenario_events(), unit_types=UNIT_TYPES, credit_usd=CREDIT_USD)
    assert ids[0] not in json.dumps(out)
    assert near(out["totals"]["credits"], 330)
    assert near(row(out["by_profile"], profile=None)["credits"], 10)  # the plain commit's 2 plus this 8


# --- properties --------------------------------------------------------------------------------------------------

RUNS = ["r_p1", "r_p2", "r_p3"]
PROFILES = [FLASH, LITE, "wide-1", None]
TIERS = ["outpost", "village", "town", "city", None]


@st.composite
def worlds(draw):
    entries = []
    for _ in range(draw(st.integers(0, 12))):
        profile = draw(st.sampled_from(PROFILES))
        usage = Usage(profile, draw(st.integers(0, 10**6)), draw(st.integers(0, 10**6))) if profile else None
        entries.append(
            LedgerEntry(
                "commit",
                draw(st.sampled_from(RUNS)),
                "u_owner",
                "org_test",
                at("2026-06-01"),
                draw(st.sampled_from(["U1", "U2", "U9", None])),
                draw(st.floats(0, 1e6, allow_nan=False)),
                usage=usage,
            )  # fmt: skip
        )
    events = []
    for i, run in enumerate(RUNS):
        tier = draw(st.sampled_from(TIERS))
        if tier:
            events.append(planned(run, tier, 100 + i))
        if draw(st.booleans()):
            events.append(completed(run, 200 + i))
    return entries, events


UNITS = {run: {"U1": "research", "U2": "draft"} for run in RUNS}


@given(worlds())
def test_FR_MTR_10_property_every_grouping_partitions_the_ledgers_spend(world):
    entries, events = world
    out = cost_report(entries, events, unit_types=UNITS, credit_usd=CREDIT_USD)
    total = math.fsum(e.credits for e in entries)
    assert out["totals"]["credits"] == total
    for key in ("tasks", "by_tier", "by_profile", "by_task_type", "by_tier_profile"):
        assert math.isclose(math.fsum(r["credits"] for r in out[key]), total, rel_tol=1e-9, abs_tol=1e-6), key
    assert all(r["tasks"] >= 1 and r["credits_per_task"] >= 0 for r in out["by_tier_profile"])
    json.dumps(out, allow_nan=False)


@given(worlds(), st.randoms(use_true_random=False))
def test_FR_MTR_10_property_input_order_never_changes_the_report(world, rng):
    entries, events = world
    shuffled_entries, shuffled_events = list(entries), list(events)
    rng.shuffle(shuffled_entries)
    rng.shuffle(shuffled_events)
    assert cost_report(shuffled_entries, shuffled_events, unit_types=UNITS, credit_usd=CREDIT_USD) == cost_report(
        entries, events, unit_types=UNITS, credit_usd=CREDIT_USD
    )


# --- credit_usd is required, and has one loader (follow-up of PR #434) -------------------------------------------


def test_FR_MTR_10_credit_usd_is_a_required_keyword_with_no_default():
    with pytest.raises(TypeError, match="credit_usd"):
        cost_report([], [], unit_types={})  # type: ignore[call-arg]


def test_FR_MTR_10_load_credit_usd_reads_the_prices_file_and_refuses_an_unreadable_one(tmp_path):
    from pathlib import Path

    from tilo_metering import MeteringConfigError
    from tilo_metering.costs import load_credit_usd

    prices = Path(__file__).resolve().parents[3] / "config" / "prices.yaml"
    assert load_credit_usd(prices) == CREDIT_USD
    with pytest.raises(MeteringConfigError):
        load_credit_usd(tmp_path / "missing.yaml")
