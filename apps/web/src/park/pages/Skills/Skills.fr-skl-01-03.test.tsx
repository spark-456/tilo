// @vitest-environment happy-dom
// Acceptance tests for AGY-SKL-1 (FR-SKL-01, FR-SKL-02, FR-SKL-03):
// - FR-SKL-01: four captured steps enable "Show me Tilo's version"; nothing is sent anywhere while teaching;
//   screen recording is a concept using fixture steps (never calls getDisplayMedia or fetch).
// - FR-SKL-02: Tilo restates the skill as steps, each with an "Ask me first" switch, one clarifying question
//   and estimates (cost per run, time, how often it stops to ask) derived from ledger prices.
// - FR-SKL-03: a try run sends and saves nothing outside Tilo; the result says how closely it matched you;
//   try-run progress only advances on fixture events, never on a timer pretending to work.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  CAP,
  EST,
  METHODS,
  PLAN,
  QUESTION,
  SCREEN,
  TRY,
} from "../../../../test-support/park/skillsCopy";
import {
  askStates,
  askSwitches,
  captureByDescribing,
  clickEl,
  control,
  currentStep,
  dropzone,
  estimate,
  finishRun,
  hasControl,
  isDisabled,
  isOn,
  methodTile,
  mountSkills,
  pageText,
  pickedCount,
  planRow,
  runPill,
  runStatuses,
  skillsApi,
  teachCard,
  textOf,
  toTilosVersion,
  toTryRun,
} from "../../../../test-support/park/skillsHarness";
import type { ApiResult } from "../../api/types";
import * as teachData from "./teachData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const liveResult = <T,>(data: T): Promise<ApiResult<T>> =>
  Promise.resolve({ data, source: "live" });

describe("FR-SKL-01: Teach by showing", () => {
  it("test_FR_SKL_01_four_captured_steps_enable_show_me_tilos_version_across_all_methods", async () => {
    const rig = await mountSkills();
    const nextBtn = () => control(rig.el, "Show me Tilo’s version");

    // Initially 0 captured steps -> disabled
    expect(pickedCount(rig.el)).toBe(0);
    expect(isDisabled(nextBtn())).toBe(true);

    // 1. Record my screen: steps 1..3 keep button disabled; step 4 enables it
    clickEl(control(rig.el, SCREEN.record.start));
    for (let step = 1; step <= 3; step++) {
      rig.clock.advance(900);
      expect(pickedCount(rig.el)).toBe(step);
      expect(pageText(teachCard(rig.el))).toContain(CAP.record[step - 1]);
      expect(isDisabled(nextBtn())).toBe(true);
    }
    rig.clock.advance(900);
    expect(pickedCount(rig.el)).toBe(4);
    expect(isDisabled(nextBtn())).toBe(false);

    // 2. Guided walkthrough: switching resets to 0 and locks; 4 captured steps enable it
    clickEl(methodTile(rig.el, "Guided walkthrough"));
    expect(pickedCount(rig.el)).toBe(0);
    expect(isDisabled(nextBtn())).toBe(true);
    clickEl(control(rig.el, SCREEN.guided.start));
    rig.clock.advance(4 * 900);
    expect(pickedCount(rig.el)).toBe(4);
    expect(isDisabled(nextBtn())).toBe(false);

    // 3. Describe it: reading description captures 4 steps and enables button
    clickEl(methodTile(rig.el, "Describe it"));
    expect(isDisabled(nextBtn())).toBe(true);
    clickEl(control(rig.el, "Read my description"));
    expect(pickedCount(rig.el)).toBe(4);
    expect(isDisabled(nextBtn())).toBe(false);

    // 4. Upload an example: clicking dropzone captures 4 steps and enables button
    clickEl(methodTile(rig.el, "Upload an example"));
    expect(isDisabled(nextBtn())).toBe(true);
    clickEl(dropzone(rig.el));
    expect(pickedCount(rig.el)).toBe(4);
    expect(isDisabled(nextBtn())).toBe(false);
  });

  it("test_FR_SKL_01_screen_recording_uses_fixture_capture_events_and_never_calls_getDisplayMedia_or_fetch", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      throw new Error("fetch must never be called during teach");
    });
    const getDisplayMedia = vi.fn(() => {
      throw new Error("getDisplayMedia must never be called");
    });
    Object.defineProperty(globalThis.navigator, "mediaDevices", {
      value: { getDisplayMedia },
      configurable: true,
    });

    const api = skillsApi();
    const rig = await mountSkills({ api });

    // Record my screen
    clickEl(control(rig.el, SCREEN.record.start));
    rig.clock.advance(4 * 900);
    expect(pickedCount(rig.el)).toBe(4);

    // Upload an example
    clickEl(methodTile(rig.el, "Upload an example"));
    clickEl(dropzone(rig.el));
    expect(pickedCount(rig.el)).toBe(4);

    expect(getDisplayMedia).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(api.saveSkill).not.toHaveBeenCalled();

    // Verify typed fixture capture event stream exists in teachData
    const captureEvents = (teachData as Record<string, unknown>).CAPTURE_FIXTURE_EVENTS as
      | Record<string, readonly { seq: number; source: string; text: string }[]>
      | undefined;
    expect(captureEvents).toBeDefined();
    for (const m of METHODS) {
      expect(captureEvents?.[m.key]).toHaveLength(4);
      expect(captureEvents?.[m.key]?.every((ev) => ev.source === "fixture")).toBe(true);
    }
  });

  it("test_FR_SKL_01_labels_teach_and_try_run_visibly_as_sample_run_whenever_source_is_fixture", async () => {
    const rig = await mountSkills();
    // Step 1 (Show it) visibly labels the capture flow as a sample run when source === "fixture"
    expect(pageText(teachCard(rig.el))).toContain("Sample run");

    // Step 3 (Try run) also visibly labels the practice run as a sample run when source === "fixture"
    toTryRun(rig);
    expect(pageText(teachCard(rig.el))).toContain("Sample run");
  });

  it("test_FR_SKL_01_non_fixture_data_offers_describing_a_skill_and_no_sample_steps_or_timers", async () => {
    const base = skillsApi();
    const api = skillsApi({
      getSkills: async () => liveResult((await base.getSkills()).data),
      getLearn: async () => liveResult((await base.getLearn()).data),
      getUser: async () => liveResult((await base.getUser()).data),
    });
    const rig = await mountSkills({ api });
    const text = pageText(teachCard(rig.el));
    expect(text).not.toMatch(/connect to start teaching/i);
    expect(text).not.toContain("Sample run");
    expect(hasControl(rig.el, "Read my description")).toBe(true);
    expect(text).toContain("0 of 0"); // nothing is captured until the server answers
    expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(true);
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
    toTilosVersion(rig);

    expect(currentStep(rig.el)).toBe("Tilo’s version");
    PLAN.forEach((p, i) => {
      const row = planRow(rig.el, i);
      expect(textOf(row)).toContain(p.text);
      expect(textOf(row)).toContain(p.tool);
    });

    const switches = askSwitches(rig.el);
    expect(switches).toHaveLength(4);
    expect(askStates(rig.el)).toEqual([false, false, true, false]);

    // Clarifying question and selectable answers
    const cardText = pageText(teachCard(rig.el));
    expect(cardText).toContain(QUESTION.eyebrow);
    expect(cardText).toContain(QUESTION.text);
    for (const ans of QUESTION.answers) {
      expect(hasControl(rig.el, ans)).toBe(true);
    }
    clickEl(control(rig.el, QUESTION.answers[0]));
    expect(isOn(control(rig.el, QUESTION.answers[0]))).toBe(true);

    // Estimates shown
    expect(estimate(rig.el, EST.runLabel)).toBe("~£0.40");
    expect(estimate(rig.el, EST.timeLabel)).toBe("~1 min");
    expect(estimate(rig.el, EST.stopsLabel)).toBe("1 step");

    // Flipping "Ask me first" updates "Stops to ask" estimate immediately
    clickEl(switches[0] as HTMLElement);
    expect(estimate(rig.el, EST.stopsLabel)).toBe("2 steps");
    clickEl(switches[0] as HTMLElement);
    clickEl(switches[2] as HTMLElement);
    expect(estimate(rig.el, EST.stopsLabel)).toBe("Never");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("test_FR_SKL_02_estimates_compute_cost_per_run_time_and_stops_to_ask_from_shared_ledger_step_prices_and_currency", async () => {
    const ledgerKpis = (await import("../../app/ledgerKpis")) as Record<string, unknown>;
    expect(ledgerKpis.STEP_LEDGER_PRICES).toEqual({
      Read: 0.05,
      Draft: 0.1,
      Act: 0.15,
    });
    expect(teachData.STEP_LEDGER_PRICES).toBe(ledgerKpis.STEP_LEDGER_PRICES);
    expect(typeof ledgerKpis.runMoney).toBe("function");

    const estimateSkillPlan = (teachData as Record<string, unknown>).estimateSkillPlan as
      | ((
          steps: readonly { readonly tool: string }[],
          asks: readonly boolean[],
          currency?: "GBP" | "USD",
        ) => { run: string; time: string; stops: string })
      | undefined;
    expect(typeof estimateSkillPlan).toBe("function");

    // Default PLAN: 2 Read (£0.05 each) + 2 Act (£0.15 each) = £0.40, 4 steps = ~1 min, 1 ask = "1 step"
    const def = estimateSkillPlan?.(teachData.PLAN, teachData.DEFAULT_ASK, "GBP");
    expect(def).toEqual({
      run: "~£0.40",
      time: "~1 min",
      stops: "1 step",
    });

    // Read-only 2-step plan in USD: 2 * 0.05 = $0.10, 30s = ~1 min, 0 asks = "Never"
    const custom = estimateSkillPlan?.(
      [{ tool: "Gmail · Read" }, { tool: "Files · Read" }],
      [false, false],
      "USD",
    );
    expect(custom).toEqual({
      run: "~$0.10",
      time: "~1 min",
      stops: "Never",
    });
  });

  it("test_FR_SKL_02_skills_reads_ledger_currency_and_shows_dollars_when_ledger_is_usd", async () => {
    const base = skillsApi();
    const usdLedger = { ...(await base.getLedger()).data, currency: "USD" as const };
    const api = skillsApi({
      getLedger: () => Promise.resolve({ data: usdLedger, source: "fixture" }),
    });
    const rig = await mountSkills({ api });

    // Library cost shows "$", not "£"
    const lib = rig.el.querySelector('section[aria-label="Learned skills"]') as HTMLElement;
    expect(pageText(lib)).toContain("$0.60 a run");
    expect(pageText(lib)).toContain("First run $2.80");
    expect(pageText(lib)).toContain("Now $0.60");
    expect(pageText(lib)).not.toContain("£0.60");
    expect(pageText(lib)).not.toContain("£2.80");

    // Skills estimate on Tilo's version shows "$", not "£"
    toTilosVersion(rig);
    expect(estimate(rig.el, EST.runLabel)).toBe("~$0.40");
    expect(pageText(teachCard(rig.el))).not.toContain("~£0.40");

    // Try-run result shows "$", not "£"
    clickEl(control(rig.el, "Let Tilo try it"));
    finishRun(rig);
    expect(pageText(teachCard(rig.el))).toContain("4 of 4 steps · 1 min 08s · $0.38");
    expect(pageText(teachCard(rig.el))).not.toContain("£0.38");
  });
});

describe("FR-SKL-03: Try run", () => {
  it("test_FR_SKL_03_try_run_sends_and_saves_nothing_outside_tilo_and_never_calls_fetch", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      throw new Error("fetch must never be called during try run");
    });
    const api = skillsApi();
    const rig = await mountSkills({ api });

    captureByDescribing(rig);
    clickEl(control(rig.el, "Show me Tilo’s version"));
    clickEl(control(rig.el, "Let Tilo try it"));
    finishRun(rig);

    expect(pageText(teachCard(rig.el))).toContain(TRY.resultTitle);
    expect(pageText(teachCard(rig.el))).toContain(TRY.resultSub);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(api.saveSkill).not.toHaveBeenCalled();
  });

  it("test_FR_SKL_03_try_run_progress_only_advances_on_fixture_events_never_on_a_timer_pretending_to_work", async () => {
    // 1. Verify TRY_RUN_FIXTURE_EVENTS and formatTryRunResult exist in teachData
    const tryEvents = (teachData as Record<string, unknown>).TRY_RUN_FIXTURE_EVENTS as
      | readonly {
          seq: number;
          type: string;
          stepIndex: number;
          matched: boolean;
          durationSec: number;
          cost: number;
          source: string;
        }[]
      | undefined;
    expect(tryEvents).toBeDefined();
    expect(tryEvents).toHaveLength(4);
    expect(tryEvents?.every((e) => e.source === "fixture" && e.type === "skill.try_run.step")).toBe(
      true,
    );

    // 2. When source is not "fixture", the Teach card describes a skill (SKILLS-5) and schedules no timers
    const base = skillsApi();
    const liveApi = skillsApi({
      getSkills: async () => liveResult((await base.getSkills()).data),
      getLearn: async () => liveResult((await base.getLearn()).data),
      getUser: async () => liveResult((await base.getUser()).data),
    });
    const rig = await mountSkills({ api: liveApi });

    expect(pageText(teachCard(rig.el))).not.toMatch(/connect to start teaching/i);
    expect(pageText(teachCard(rig.el))).not.toContain("Sample run");
    expect(rig.clock.live()).toHaveLength(0);
    rig.clock.advance(60_000);
    expect(rig.clock.live()).toHaveLength(0);
    expect(pageText(teachCard(rig.el))).not.toContain(TRY.resultTitle);
  });

  it("test_FR_SKL_03_try_run_result_reports_how_closely_it_matched_you_from_fixture_events", () => {
    const formatTryRunResult = (teachData as Record<string, unknown>).formatTryRunResult as
      | ((
          events: readonly {
            matched: boolean;
            durationSec: number;
            cost: number;
          }[],
          totalSteps?: number,
          currency?: "GBP" | "USD",
        ) => { title: string; sub: string })
      | undefined;
    expect(typeof formatTryRunResult).toBe("function");

    const tryEvents = (teachData as Record<string, unknown>).TRY_RUN_FIXTURE_EVENTS as readonly {
      matched: boolean;
      durationSec: number;
      cost: number;
    }[];
    // Full match on the 4 fixture events
    expect(formatTryRunResult?.(tryEvents, 4)).toEqual({
      title: "Matched your way of doing it",
      sub: "4 of 4 steps · 1 min 08s · £0.38",
    });

    // Partial match (3 of 4 steps matched) and USD currency support via shared ledger formatter
    const partial = tryEvents.map((e, i) => (i === 3 ? { ...e, matched: false } : e));
    expect(formatTryRunResult?.(partial, 4, "USD")).toEqual({
      title: "Matched 3 of 4 steps of your way",
      sub: "3 of 4 steps · 1 min 08s · $0.38",
    });
  });
});
