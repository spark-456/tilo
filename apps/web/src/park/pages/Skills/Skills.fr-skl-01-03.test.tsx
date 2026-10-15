// @vitest-environment happy-dom
// Acceptance tests for AGY-SKL-1 (FR-SKL-01, FR-SKL-02, FR-SKL-03), on the STUDIO-4 Teach wizard:
// - FR-SKL-01: teach by describing it (step 1); the read steps show on step 2, labelled a sample on sample data;
//   nothing is sent anywhere while teaching on sample data; an example file or a screen recording has no route yet,
//   so it is off and says so (never getDisplayMedia, never fetch).
// - FR-SKL-02: Tilo restates the skill as steps, each with an "Ask me first" switch, one clarifying question
//   and estimates (cost per run, time, how often it stops to ask) derived from ledger prices.
// - FR-SKL-03: a try run sends and saves nothing outside Tilo. It has no route yet (STUDIO-4), so "Try it once"
//   is off, says so, and nothing pretends to run (no timer, no progress).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import { CAP, EST, PLAN, QUESTION } from "../../../../test-support/park/skillsCopy";
import {
  NEXT_EXAMPLE,
  askStates,
  askSwitches,
  clickEl,
  control,
  currentStep,
  describeField,
  estimate,
  hasControl,
  isDisabled,
  isOn,
  mountSkills,
  openSkill,
  openTeach,
  pageText,
  skillsApi,
  teachCard,
  toExample,
  toReview,
  typeInto,
} from "../../../../test-support/park/skillsHarness";
import type { ApiResult } from "../../api/types";
import { EXAMPLE_OFF, TRY_OFF } from "./TeachWizard";
import * as teachData from "./teachData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const liveResult = <T,>(data: T): Promise<ApiResult<T>> =>
  Promise.resolve({ data, source: "live" });

describe("FR-SKL-01: Teach by describing", () => {
  it("test_FR_SKL_01_describing_reads_the_steps_and_moves_to_show_an_example_without_any_request", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      throw new Error("fetch must never be called while teaching on sample data");
    });
    const rig = await mountSkills();
    openTeach(rig);
    expect(currentStep(rig.el)).toBe("Describe it");
    expect(describeField(rig.el).value).not.toBe(""); // the sample description
    clickEl(control(rig.el, NEXT_EXAMPLE));
    expect(currentStep(rig.el)).toBe("Show an example");
    for (const step of CAP.describe) expect(pageText(teachCard(rig.el))).toContain(step);
    expect(pageText(teachCard(rig.el))).toContain(teachData.DESCRIBE_SAMPLE); // labelled a sample
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(rig.clock.live()).toHaveLength(0);
  });

  it("test_FR_SKL_01_an_example_or_a_screen_recording_is_off_and_says_so_and_never_records", async () => {
    const media = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getDisplayMedia: media },
    });
    const rig = await mountSkills();
    toExample(rig);
    const record = control(rig.el, "Start recording");
    expect(isDisabled(record)).toBe(true);
    clickEl(record);
    expect(media).not.toHaveBeenCalled();
    expect(pageText(teachCard(rig.el))).toContain(EXAMPLE_OFF);
  });

  it("test_FR_SKL_01_an_empty_description_cannot_move_on_and_says_what_is_missing", async () => {
    const rig = await mountSkills();
    openTeach(rig);
    const field = describeField(rig.el);
    typeInto(field, "  ");
    expect(isDisabled(control(rig.el, NEXT_EXAMPLE))).toBe(true);
    expect(pageText(teachCard(rig.el))).toContain("Write a sentence about the work first.");
  });

  it("test_FR_SKL_01_non_fixture_data_offers_describing_a_skill_and_no_sample_steps_or_timers", async () => {
    const base = skillsApi();
    const api = skillsApi({
      getSkills: async () => liveResult((await base.getSkills()).data),
      getLearn: async () => liveResult((await base.getLearn()).data),
      getUser: async () => liveResult((await base.getUser()).data),
    });
    const rig = await mountSkills({ api });
    openTeach(rig);
    const text = pageText(teachCard(rig.el));
    expect(text).not.toContain(teachData.DESCRIBE_SAMPLE);
    expect(describeField(rig.el).value).toBe("");
    expect(isDisabled(control(rig.el, NEXT_EXAMPLE))).toBe(true);
    expect(rig.clock.live()).toHaveLength(0);
    rig.clock.advance(10_000);
    expect(rig.clock.live()).toHaveLength(0);
  });
});

describe("FR-SKL-02: Tilo's version", () => {
  it("test_FR_SKL_02_tilos_version_restates_skill_as_steps_with_ask_me_first_switches_and_clarifying_question", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      throw new Error("fetch must never be called during Tilo's version");
    });
    const rig = await mountSkills();
    toReview(rig);

    expect(currentStep(rig.el)).toBe("Review the steps");
    const card = pageText(teachCard(rig.el));
    for (const p of PLAN) {
      expect(card).toContain(p.text);
      expect(card).toContain(p.tool);
    }
    const switches = askSwitches(rig.el);
    expect(switches).toHaveLength(4);
    expect(askStates(rig.el)).toEqual([false, false, true, false]);

    expect(card).toContain(QUESTION.eyebrow);
    expect(card).toContain(QUESTION.text);
    for (const ans of QUESTION.answers) expect(hasControl(rig.el, ans)).toBe(true);
    clickEl(control(rig.el, QUESTION.answers[0]));
    expect(isOn(control(rig.el, QUESTION.answers[0]))).toBe(true);

    expect(estimate(rig.el, EST.runLabel)).toBe("~£0.40");
    expect(estimate(rig.el, EST.timeLabel)).toBe("~1 min");
    expect(estimate(rig.el, EST.stopsLabel)).toBe("1 step");
    clickEl(switches[0] as HTMLElement);
    expect(estimate(rig.el, EST.stopsLabel)).toBe("2 steps");
    clickEl(switches[0] as HTMLElement);
    clickEl(switches[2] as HTMLElement);
    expect(estimate(rig.el, EST.stopsLabel)).toBe("Never");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("test_FR_SKL_02_estimates_compute_cost_per_run_time_and_stops_to_ask_from_shared_ledger_step_prices_and_currency", async () => {
    const ledgerKpis = (await import("../../app/ledgerKpis")) as Record<string, unknown>;
    expect(ledgerKpis.STEP_LEDGER_PRICES).toEqual({ Read: 0.05, Draft: 0.1, Act: 0.15 });
    expect(teachData.STEP_LEDGER_PRICES).toBe(ledgerKpis.STEP_LEDGER_PRICES);
    // Default PLAN: 2 Read (£0.05 each) + 2 Act (£0.15 each) = £0.40, 4 steps = ~1 min, 1 ask = "1 step"
    expect(teachData.estimateSkillPlan(teachData.PLAN, teachData.DEFAULT_ASK, "GBP")).toEqual({
      run: "~£0.40",
      time: "~1 min",
      stops: "1 step",
    });
    // Read-only 2-step plan in USD: 2 * 0.05 = $0.10, 30s = ~1 min, 0 asks = "Never"
    expect(
      teachData.estimateSkillPlan(
        [{ tool: "Gmail · Read" }, { tool: "Files · Read" }],
        [false, false],
        "USD",
      ),
    ).toEqual({ run: "~$0.10", time: "~1 min", stops: "Never" });
  });

  it("test_FR_SKL_02_skills_reads_ledger_currency_and_shows_dollars_when_ledger_is_usd", async () => {
    const base = skillsApi();
    const usdLedger = { ...(await base.getLedger()).data, currency: "USD" as const };
    const api = skillsApi({
      getLedger: () => Promise.resolve({ data: usdLedger, source: "fixture" }),
    });
    const rig = await mountSkills({ api });

    const sheet = openSkill(rig.el, "Match invoices to purchase orders");
    expect(pageText(sheet)).toContain("$0.60");
    expect(pageText(sheet)).toContain("First run $2.80 · Now $0.60");
    expect(pageText(sheet)).not.toContain("£0.60");
    clickEl(sheet.querySelector('button[aria-label="Close"]') as HTMLElement);

    toReview(rig);
    expect(estimate(rig.el, EST.runLabel)).toBe("~$0.40");
    expect(pageText(teachCard(rig.el))).not.toContain("~£0.40");
  });
});

describe("FR-SKL-03: Try run", () => {
  it("test_FR_SKL_03_try_run_is_off_says_so_and_sends_saves_and_schedules_nothing", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      throw new Error("fetch must never be called during a try run");
    });
    const api = skillsApi();
    const rig = await mountSkills({ api });
    toReview(rig);
    const tryIt = control(rig.el, "Try it once");
    expect(isDisabled(tryIt)).toBe(true);
    expect(pageText(teachCard(rig.el))).toContain(TRY_OFF);
    clickEl(tryIt);
    rig.clock.advance(60_000);
    expect(rig.clock.live()).toHaveLength(0);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(api.saveSkill).not.toHaveBeenCalled();
    expect(currentStep(rig.el)).toBe("Review the steps");
  });

  it("test_FR_SKL_03_a_skill_in_the_gallery_offers_no_test_run_either", async () => {
    const rig = await mountSkills();
    const sheet = openSkill(rig.el, "Match invoices to purchase orders");
    const run = control(sheet, "Test run");
    expect(isDisabled(run)).toBe(true);
    clickEl(run);
    expect(rig.clock.live()).toHaveLength(0);
  });
});
