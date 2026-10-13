// @vitest-environment happy-dom
// WEB-8a acceptance: the "Teach Tilo something new" flow as a state machine (README "Skills" item 2, the
// reference page's `renderVals` and its `startCapture` / `startRun` / `advance`): Show it -> Tilo's version ->
// Try run -> Save -> saved. Every timed part goes through the injected scheduler (`useSchedule`), so this file
// drives a virtual clock and never waits. Pinned to the design's numbers: a captured step every 900 ms, a run
// step every 900 ms, step 3 asks first by default, the estimates, the result line, the saved line, the toast.
// Where the design and the task text differ the design wins (see the WEB-8a report): the scope and trigger
// pickers are found as radios or plain buttons; "Save" before a finished run is locked; back from Save lands
// on Try run (what the run then shows is not pinned: the reference leaves it unfinished).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, nameOf, qa } from "../../../../test-support/park/componentsHarness";
import {
  CAP,
  CAPTURED_HINT,
  DEFAULT_ASK,
  DEFAULT_DESC,
  DEFAULT_NAME,
  DESCRIBE_HELP,
  DROP,
  EST,
  LEARN_NOTE,
  METHODS,
  NO_STEPS_YET,
  PLAN,
  QUESTION,
  SAVE,
  SAVED_OVERRIDE,
  SCREEN,
  STEP_LABELS,
  type Scope,
  TRY,
  type Trigger,
  savedLine,
  savedTitle,
  savedToast,
} from "../../../../test-support/park/skillsCopy";
import {
  type SkillsRig,
  agentArt,
  artIn,
  askStates,
  askSwitches,
  captureByDescribing,
  choice,
  clickEl,
  control,
  currentStep,
  describeField,
  deskArt,
  dropzone,
  elWithText,
  estimate,
  finishRun,
  flat,
  goCalls,
  hasControl,
  isDisabled,
  isOn,
  methodTile,
  mountSkills,
  pageText,
  pickedCount,
  planRow,
  press,
  reachable,
  rejects,
  runPill,
  runStatuses,
  settle,
  skillNameField,
  skillsApi,
  stepButton,
  teachCard,
  textOf,
  toSave,
  toTilosVersion,
  toTryRun,
  toasts,
  typeInto,
} from "../../../../test-support/park/skillsHarness";
import { skills } from "../../api/fixtures";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const tap = (rig: SkillsRig, label: string) => clickEl(control(rig.el, label));
const card = (rig: SkillsRig) => pageText(teachCard(rig.el));
const showsAll = (rig: SkillsRig, lines: readonly string[]) => {
  for (const l of lines) expect(card(rig), l).toContain(l);
};
const recLabel = (rig: SkillsRig): string | undefined => card(rig).match(/REC 00:0\d/)?.[0];
const log = (() => {
  const hit = skills.find((s) => s.id === "log");
  if (!hit) throw new Error("no draft skill `log` in the fixtures");
  return hit;
})();

describe("WEB_8a_skills_teach: how to show it (step 1)", () => {
  it.each(METHODS.map((m) => m.name))(
    "WEB_8a_skills_teach_picking_%s_selects_it_and_only_it",
    async (name) => {
      const rig = await mountSkills();
      clickEl(methodTile(rig.el, name));
      for (const m of METHODS)
        expect(isOn(methodTile(rig.el, m.name)), m.name).toBe(m.name === name);
    },
  );

  it("WEB_8a_skills_teach_Guided_walkthrough_has_its_own_address_hint_and_start_label", async () => {
    const rig = await mountSkills();
    clickEl(methodTile(rig.el, "Guided walkthrough"));
    showsAll(rig, [SCREEN.guided.url, SCREEN.guided.hint]);
    expect(hasControl(rig.el, SCREEN.guided.start)).toBe(true);
    expect(card(rig)).not.toContain(SCREEN.record.url);
  });

  it("WEB_8a_skills_teach_Describe_it_has_the_task_field_the_help_line_and_Read_my_description", async () => {
    const rig = await mountSkills();
    clickEl(methodTile(rig.el, "Describe it"));
    expect(describeField(rig.el).value).toBe(DEFAULT_DESC);
    showsAll(rig, [DESCRIBE_HELP]);
    expect(hasControl(rig.el, "Read my description")).toBe(true);
    expect(card(rig)).not.toContain(SCREEN.record.url);
  });

  it("WEB_8a_skills_teach_what_is_typed_in_the_task_field_is_kept_across_methods", async () => {
    const rig = await mountSkills();
    clickEl(methodTile(rig.el, "Describe it"));
    typeInto(describeField(rig.el), "Pay the Northline invoice on the due date.");
    clickEl(methodTile(rig.el, "Upload an example"));
    clickEl(methodTile(rig.el, "Describe it"));
    expect(describeField(rig.el).value).toBe("Pay the Northline invoice on the due date.");
  });

  it("WEB_8a_skills_teach_Upload_an_example_shows_the_dropzone_until_it_is_clicked", async () => {
    const rig = await mountSkills();
    clickEl(methodTile(rig.el, "Upload an example"));
    showsAll(rig, [DROP.title, DROP.sub]);
    expect(pickedCount(rig.el)).toBe(0);
    clickEl(dropzone(rig.el));
    expect(pickedCount(rig.el)).toBe(4);
    showsAll(rig, [DROP.doneTitle, DROP.doneSub, ...CAP.upload]);
    expect(card(rig)).not.toContain(DROP.sub);
    expect(rig.clock.timers).toHaveLength(0); // an upload is read at once, nothing is scheduled
  });

  it("WEB_8a_skills_teach_Read_my_description_captures_the_four_steps_at_once_with_no_timer", async () => {
    const rig = await mountSkills();
    clickEl(methodTile(rig.el, "Describe it"));
    expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(true);
    tap(rig, "Read my description");
    expect(pickedCount(rig.el)).toBe(4);
    showsAll(rig, CAP.describe);
    expect(card(rig)).not.toContain(NO_STEPS_YET);
    expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(false);
    expect(rig.clock.timers).toHaveLength(0);
  });

  it("WEB_8a_skills_teach_changing_the_method_forgets_the_captured_steps_and_locks_the_next_step_again", async () => {
    const rig = await mountSkills();
    captureByDescribing(rig);
    clickEl(methodTile(rig.el, "Upload an example"));
    expect(pickedCount(rig.el)).toBe(0);
    expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(true);
    expect(reachable(rig.el)).toEqual([true, false, false, false]);
  });

  it("WEB_8a_skills_teach_the_skill_name_is_editable_and_starts_as_the_designs_example", async () => {
    const rig = await mountSkills();
    expect(skillNameField(rig.el).value).toBe(DEFAULT_NAME);
    typeInto(skillNameField(rig.el), "Pay supplier invoices");
    expect(skillNameField(rig.el).value).toBe("Pay supplier invoices");
  });
});

describe("WEB_8a_skills_teach: recording (a captured step every 900 ms)", () => {
  it.each(["record", "guided"] as const)(
    "WEB_8a_skills_teach_%s_captures_one_step_every_900ms_and_unlocks_the_next_step_only_at_four",
    async (key) => {
      const rig = await mountSkills();
      if (key === "guided") clickEl(methodTile(rig.el, "Guided walkthrough"));
      tap(rig, SCREEN[key].start);
      expect(rig.clock.timers[0]?.ms).toBe(900);
      expect(rig.clock.timers.every((t) => t.ms % 900 === 0 && t.ms > 0)).toBe(true);
      expect(pickedCount(rig.el)).toBe(0);
      expect(recLabel(rig)).toBe("REC 00:02");
      expect(isDisabled(control(rig.el, "Recording…"))).toBe(true);
      expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(true);
      rig.clock.advance(899);
      expect(pickedCount(rig.el)).toBe(0);
      for (let n = 1; n <= 3; n++) {
        rig.clock.advance(n === 1 ? 1 : 900);
        expect(pickedCount(rig.el), `after ${n} x 900 ms`).toBe(n);
        expect(recLabel(rig)).toBe(`REC 00:0${2 + 2 * n}`);
        showsAll(rig, CAP[key].slice(0, n));
        expect(card(rig)).not.toContain(CAP[key][n] ?? "never");
        expect(isDisabled(control(rig.el, "Show me Tilo’s version")), `after ${n}`).toBe(true);
        expect(reachable(rig.el)).toEqual([true, false, false, false]);
      }
      rig.clock.advance(900);
      expect(pickedCount(rig.el)).toBe(4);
      showsAll(rig, CAP[key]);
      expect(recLabel(rig)).toBeUndefined();
      expect(hasControl(rig.el, "Record again")).toBe(true);
      expect(card(rig)).toContain(CAPTURED_HINT);
      expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(false);
      expect(reachable(rig.el)).toEqual([true, true, true, false]);
      expect(rig.clock.live()).toHaveLength(0); // nothing keeps ticking once it has the four
    },
  );

  it("WEB_8a_skills_teach_Record_again_starts_over_from_none", async () => {
    const rig = await mountSkills();
    tap(rig, "Start recording");
    rig.clock.advance(4 * 900);
    tap(rig, "Record again");
    expect(pickedCount(rig.el)).toBe(0);
    expect(recLabel(rig)).toBe("REC 00:02");
    expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(true);
    rig.clock.advance(900);
    expect(pickedCount(rig.el)).toBe(1);
  });

  it("WEB_8a_skills_teach_a_press_on_Recording_while_recording_does_nothing", async () => {
    const rig = await mountSkills();
    tap(rig, "Start recording");
    clickEl(control(rig.el, "Recording…"));
    rig.clock.advance(900);
    expect(pickedCount(rig.el)).toBe(1); // not two steps at once, not a second clock
    expect(rig.clock.live().length).toBeLessThanOrEqual(1);
  });

  it("WEB_8a_skills_teach_changing_the_method_mid_recording_stops_it_and_its_timer", async () => {
    const rig = await mountSkills();
    tap(rig, "Start recording");
    rig.clock.advance(1000);
    clickEl(methodTile(rig.el, "Describe it"));
    expect(rig.clock.live()).toHaveLength(0);
    rig.clock.advance(10_000);
    expect(pickedCount(rig.el)).toBe(0);
    expect(card(rig)).not.toMatch(/REC 00:/);
  });

  it("WEB_8a_skills_teach_leaving_the_page_mid_recording_cancels_its_timer_without_an_error", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const rig = await mountSkills();
    tap(rig, "Start recording");
    rig.clock.advance(900);
    rig.m.unmount();
    expect(rig.clock.live()).toHaveLength(0);
    rig.clock.advance(10_000);
    expect(error).not.toHaveBeenCalled();
  });
});

describe("WEB_8a_skills_teach: the step bar (earlier steps can be revisited)", () => {
  it("WEB_8a_skills_teach_the_steps_after_Show_it_open_once_four_steps_are_captured_and_Save_waits_for_a_run", async () => {
    const rig = await mountSkills();
    captureByDescribing(rig);
    expect(reachable(rig.el)).toEqual([true, true, true, false]);
  });

  it("WEB_8a_skills_teach_pressing_a_locked_step_does_nothing", async () => {
    const rig = await mountSkills();
    clickEl(stepButton(rig.el, "Tilo’s version"));
    clickEl(stepButton(rig.el, "Save"));
    expect(currentStep(rig.el)).toBe("Show it");
  });

  it("WEB_8a_skills_teach_the_current_marker_follows_the_flow_and_an_earlier_step_can_be_revisited", async () => {
    const rig = await mountSkills();
    captureByDescribing(rig);
    clickEl(stepButton(rig.el, "Tilo’s version"));
    expect(currentStep(rig.el)).toBe("Tilo’s version");
    expect(qa(teachCard(rig.el), '[aria-current="step"]')).toHaveLength(1);
    clickEl(stepButton(rig.el, "Show it"));
    expect(currentStep(rig.el)).toBe("Show it");
    expect(pickedCount(rig.el)).toBe(4); // what was captured is still there
    expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(false);
  });

  it("WEB_8a_skills_teach_Try_run_can_be_opened_straight_from_the_bar_and_starts_the_run", async () => {
    const rig = await mountSkills();
    captureByDescribing(rig);
    clickEl(stepButton(rig.el, "Try run"));
    expect(currentStep(rig.el)).toBe("Try run");
    expect(runStatuses(rig.el)).toEqual(["Working…", "Waiting", "Waiting", "Waiting"]);
    expect(reachable(rig.el)).toEqual([true, true, true, false]);
  });

  it("WEB_8a_skills_teach_Show_me_Tilos_version_moves_to_step_2", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    expect(currentStep(rig.el)).toBe("Tilo’s version");
  });
});

describe("WEB_8a_skills_teach: Tilo's version (step 2)", () => {
  it("WEB_8a_skills_teach_the_bubble_names_the_skill_in_bold_and_follows_the_name_as_edited", async () => {
    const rig = await mountSkills();
    typeInto(skillNameField(rig.el), "Pay Northline");
    toTilosVersion(rig);
    const bubble = qa(teachCard(rig.el), "div, p, span").find(
      (e) =>
        textOf(e) ===
        "Here’s how I’d do Pay Northline. Change anything that looks wrong, and tell me where to stop and ask you.",
    );
    expect(bubble, "the speech bubble").toBeDefined();
    expect(textOf(bubble?.querySelector("b") as HTMLElement)).toBe("Pay Northline");
  });

  it("WEB_8a_skills_teach_four_plan_steps_in_order_each_with_its_tool_and_level", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    PLAN.forEach((p, i) => {
      const row = planRow(rig.el, i);
      expect(textOf(row), p.text).toContain(p.tool);
      expect(
        flat(textOf(row)).startsWith(`${i + 1}${flat(p.text)}`),
        `step ${i + 1} is numbered`,
      ).toBe(true);
    });
    const at = PLAN.map((p) => card(rig).indexOf(p.text));
    expect([...at].sort((a, b) => a - b)).toEqual(at);
  });

  it("WEB_8a_skills_teach_each_plan_step_has_an_Ask_me_first_switch_and_step_3_is_on_by_default", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    const switches = askSwitches(rig.el);
    expect(switches).toHaveLength(4);
    for (const s of switches) expect(flat(nameOf(s))).toBe("Askmefirst");
    expect(card(rig).split("Ask me first").length - 1).toBeGreaterThanOrEqual(4); // each row says it in words
    expect(askStates(rig.el)).toEqual([...DEFAULT_ASK]);
  });

  it("WEB_8a_skills_teach_a_switch_flips_alone_by_click_and_by_Space_and_Enter", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    clickEl(askSwitches(rig.el)[0] as HTMLElement);
    expect(askStates(rig.el)).toEqual([true, false, true, false]);
    press(askSwitches(rig.el)[2] as HTMLElement, " ");
    expect(askStates(rig.el)).toEqual([true, false, false, false]);
    press(askSwitches(rig.el)[3] as HTMLElement, "Enter");
    expect(askStates(rig.el)).toEqual([true, false, false, true]);
  });

  it.each([
    [[], "Never"],
    [[2], "1 step"],
    [[0, 2], "2 steps"],
    [[0, 1, 2, 3], "4 steps"],
  ] as const)(
    "WEB_8a_skills_teach_asking_first_on_steps_%j_reads_Stops_to_ask_%s",
    async (on, want) => {
      const rig = await mountSkills();
      toTilosVersion(rig);
      askStates(rig.el).forEach((now, i) => {
        if (now !== on.some((j) => j === i)) clickEl(askSwitches(rig.el)[i] as HTMLElement);
      });
      expect(estimate(rig.el, EST.stopsLabel)).toBe(want);
    },
  );

  it("WEB_8a_skills_teach_the_estimates_are_about_40p_a_run_and_a_minute", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    expect(estimate(rig.el, EST.runLabel)).toBe(EST.runValue);
    expect(estimate(rig.el, EST.timeLabel)).toBe(EST.timeValue);
    expect(estimate(rig.el, EST.stopsLabel)).toBe("1 step");
  });

  it("WEB_8a_skills_teach_one_question_with_three_pill_answers_none_chosen_and_one_at_a_time", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    showsAll(rig, [QUESTION.eyebrow, QUESTION.text, LEARN_NOTE]);
    const on = () => QUESTION.answers.map((a) => isOn(control(rig.el, a)));
    expect(on()).toEqual([false, false, false]);
    tap(rig, "Ask me each time");
    expect(on()).toEqual([false, true, false]);
    tap(rig, "Skip and flag it");
    expect(on()).toEqual([false, false, true]);
    tap(rig, "Skip and flag it");
    expect(on()).toEqual([false, false, true]);
  });

  it("WEB_8a_skills_teach_Back_returns_to_Show_it_with_the_captured_steps_and_the_name_kept", async () => {
    const rig = await mountSkills();
    typeInto(skillNameField(rig.el), "Pay Northline");
    toTilosVersion(rig);
    tap(rig, "Back");
    expect(currentStep(rig.el)).toBe("Show it");
    expect(pickedCount(rig.el)).toBe(4);
    expect(skillNameField(rig.el).value).toBe("Pay Northline");
  });

  it("WEB_8a_skills_teach_the_asks_and_the_answer_are_kept_when_going_on_and_coming_back", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    clickEl(askSwitches(rig.el)[0] as HTMLElement);
    tap(rig, "Open the link");
    tap(rig, "Let Tilo try it");
    clickEl(stepButton(rig.el, "Tilo’s version"));
    expect(askStates(rig.el)).toEqual([true, false, true, false]);
    expect(isOn(control(rig.el, "Open the link"))).toBe(true);
  });

  it("WEB_8a_skills_teach_the_pictures_are_the_builder_lead_talking_and_the_puzzled_builder", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    const art = await artIn(teachCard(rig.el));
    expect(art).toContain(await agentArt({ role: "builder", rank: "lead", expr: "talking" }, 40));
    expect(art).toContain(await agentArt({ role: "builder", expr: "puzzled" }, 38));
  });
});

describe("WEB_8a_skills_teach: the try run (step 3; a run step every 900 ms)", () => {
  it("WEB_8a_skills_teach_Let_Tilo_try_it_opens_the_practice_run_with_step_1_working", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    tap(rig, "Let Tilo try it");
    expect(currentStep(rig.el)).toBe("Try run");
    showsAll(rig, [TRY.practice]);
    expect(runPill(rig.el)).toBe("Step 1 of 4");
    expect(runStatuses(rig.el)).toEqual(["Working…", "Waiting", "Waiting", "Waiting"]);
    PLAN.forEach((p, i) => expect(card(rig), `step ${i + 1}`).toContain(p.text));
  });

  it("WEB_8a_skills_teach_with_the_default_asks_the_run_advances_every_900ms_then_stops_to_ask_at_step_3", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    expect(rig.clock.timers[0]?.ms).toBe(900);
    expect(rig.clock.timers.every((t) => t.ms % 900 === 0 && t.ms > 0)).toBe(true);
    rig.clock.advance(899);
    expect(runStatuses(rig.el)).toEqual(["Working…", "Waiting", "Waiting", "Waiting"]);
    rig.clock.advance(1);
    expect(runStatuses(rig.el)).toEqual(["Done", "Working…", "Waiting", "Waiting"]);
    expect(runPill(rig.el)).toBe("Step 2 of 4");
    rig.clock.advance(900);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Working…", "Waiting"]);
    expect(runPill(rig.el)).toBe("Step 3 of 4");
    rig.clock.advance(900);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Asking you", "Waiting"]);
    expect(runPill(rig.el)).toBe("Waiting for you");
    expect(hasControl(rig.el, TRY.yes)).toBe(true);
    expect(card(rig)).toContain(`Add ${TRY.prompt} to Invoices 2026?`);
  });

  it("WEB_8a_skills_teach_a_run_that_is_waiting_for_the_person_does_not_move_on_by_itself", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    rig.clock.advance(3 * 900);
    rig.clock.advance(60_000);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Asking you", "Waiting"]);
    expect(runPill(rig.el)).toBe("Waiting for you");
    expect(card(rig)).not.toContain(TRY.resultTitle);
  });

  it("WEB_8a_skills_teach_Yes_add_it_lets_step_3_finish_and_the_last_step_follows_900ms_later", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    rig.clock.advance(3 * 900);
    tap(rig, TRY.yes);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Done", "Working…"]);
    expect(runPill(rig.el)).toBe("Step 4 of 4");
    expect(hasControl(rig.el, TRY.yes)).toBe(false);
    rig.clock.advance(899);
    expect(runStatuses(rig.el)[3]).toBe("Working…");
    rig.clock.advance(1);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Done", "Done"]);
    expect(runPill(rig.el)).toBe("Finished");
    expect(rig.clock.live()).toHaveLength(0);
  });

  it("WEB_8a_skills_teach_the_result_reads_matched_4_of_4_steps_1_min_08s_and_40p_less_2p", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    expect(card(rig)).not.toContain(TRY.resultTitle);
    expect(hasControl(rig.el, "Looks right")).toBe(false);
    finishRun(rig);
    showsAll(rig, [TRY.resultTitle, TRY.resultSub]);
    expect(hasControl(rig.el, "Fix a step")).toBe(true);
    expect(hasControl(rig.el, "Looks right")).toBe(true);
  });

  it("WEB_8a_skills_teach_with_no_step_set_to_ask_first_the_run_finishes_at_3600ms_without_a_question", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    clickEl(askSwitches(rig.el)[2] as HTMLElement);
    tap(rig, "Let Tilo try it");
    rig.clock.advance(3599);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Done", "Working…"]);
    expect(card(rig)).not.toContain("Asking you");
    rig.clock.advance(1);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Done", "Done"]);
    expect(card(rig)).toContain(TRY.resultTitle);
  });

  it("WEB_8a_skills_teach_a_step_set_to_ask_first_stops_the_run_when_it_gets_there_not_before", async () => {
    const rig = await mountSkills();
    toTilosVersion(rig);
    clickEl(askSwitches(rig.el)[0] as HTMLElement);
    tap(rig, "Let Tilo try it");
    rig.clock.advance(899);
    expect(runStatuses(rig.el)[0]).toBe("Working…");
    rig.clock.advance(1);
    expect(runStatuses(rig.el)).toEqual(["Asking you", "Waiting", "Waiting", "Waiting"]);
    expect(runPill(rig.el)).toBe("Waiting for you");
    tap(rig, TRY.yes);
    expect(runStatuses(rig.el)).toEqual(["Done", "Working…", "Waiting", "Waiting"]);
    rig.clock.advance(900);
    rig.clock.advance(900);
    expect(runStatuses(rig.el)).toEqual(["Done", "Done", "Asking you", "Waiting"]);
  });

  it("WEB_8a_skills_teach_Save_stays_locked_until_the_run_has_finished", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    expect(reachable(rig.el)[3]).toBe(false);
    rig.clock.advance(3 * 900);
    expect(reachable(rig.el)[3]).toBe(false);
    tap(rig, TRY.yes);
    rig.clock.advance(900);
    expect(reachable(rig.el)).toEqual([true, true, true, true]);
  });

  it("WEB_8a_skills_teach_Fix_a_step_goes_back_to_Tilos_version_and_Let_Tilo_try_it_starts_a_fresh_run", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    finishRun(rig);
    tap(rig, "Fix a step");
    expect(currentStep(rig.el)).toBe("Tilo’s version");
    expect(rig.clock.live()).toHaveLength(0);
    tap(rig, "Let Tilo try it");
    expect(runStatuses(rig.el)).toEqual(["Working…", "Waiting", "Waiting", "Waiting"]);
    expect(runPill(rig.el)).toBe("Step 1 of 4");
    expect(card(rig)).not.toContain(TRY.resultTitle);
  });

  it("WEB_8a_skills_teach_leaving_the_run_by_the_step_bar_cancels_it_and_coming_back_restarts_it", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    rig.clock.advance(1000);
    clickEl(stepButton(rig.el, "Tilo’s version"));
    expect(rig.clock.live()).toHaveLength(0);
    rig.clock.advance(60_000);
    clickEl(stepButton(rig.el, "Try run"));
    expect(runStatuses(rig.el)).toEqual(["Working…", "Waiting", "Waiting", "Waiting"]);
  });

  it("WEB_8a_skills_teach_leaving_the_page_mid_run_cancels_its_timer_without_an_error", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const rig = await mountSkills();
    toTryRun(rig);
    rig.clock.advance(900);
    rig.m.unmount();
    expect(rig.clock.live()).toHaveLength(0);
    rig.clock.advance(60_000);
    expect(error).not.toHaveBeenCalled();
  });

  it("WEB_8a_skills_teach_the_run_panel_draws_the_desk_and_the_lead_builder_as_the_run_goes", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    const art = () => artIn(teachCard(rig.el));
    const lead = (expr: string, ring: boolean) =>
      agentArt({ role: "builder", rank: "lead", expr, ring, facing: "R" }, 96);
    expect(await art()).toContain(await deskArt("active"));
    expect(await art()).toContain(await lead("focused", false));
    rig.clock.advance(3 * 900);
    expect(await art()).toContain(await deskArt("needs"));
    expect(await art()).toContain(await lead("needs", true));
    tap(rig, TRY.yes);
    rig.clock.advance(900);
    expect(await art()).toContain(await deskArt("complete"));
    expect(await art()).toContain(await lead("delighted", false));
  });

  it("WEB_8a_skills_teach_the_header_teacher_is_focused_during_the_run_and_delighted_once_saved", async () => {
    const rig = await mountSkills();
    const teacher = (expr: string) => agentArt({ role: "research", rank: "lead", expr }, 58);
    toTryRun(rig);
    expect(await artIn(teachCard(rig.el))).toContain(await teacher("focused"));
    finishRun(rig);
    clickEl(control(rig.el, "Looks right"));
    expect(await artIn(teachCard(rig.el))).toContain(await teacher("talking")); // back to talking off the run
    tap(rig, "Save skill");
    expect(await artIn(teachCard(rig.el))).toContain(await teacher("delighted"));
  });

  it("WEB_8a_skills_teach_Looks_right_opens_Save_and_Back_from_Save_returns_to_Try_run", async () => {
    const rig = await mountSkills();
    toTryRun(rig);
    finishRun(rig);
    tap(rig, "Looks right");
    expect(currentStep(rig.el)).toBe("Save");
    tap(rig, "Back");
    expect(currentStep(rig.el)).toBe("Try run");
  });

  it("WEB_8a_skills_teach_opening_Try_run_again_from_the_bar_after_a_finished_run_restarts_it_and_locks_Save", async () => {
    const rig = await mountSkills();
    toSave(rig);
    clickEl(stepButton(rig.el, "Try run"));
    expect(runStatuses(rig.el)).toEqual(["Working…", "Waiting", "Waiting", "Waiting"]);
    expect(reachable(rig.el)[3]).toBe(false);
  });
});

describe("WEB_8a_skills_teach: save (step 4)", () => {
  it("WEB_8a_skills_teach_the_form_offers_name_scope_and_trigger_with_the_designs_defaults", async () => {
    const rig = await mountSkills();
    toSave(rig);
    expect(currentStep(rig.el)).toBe("Save");
    showsAll(rig, [SAVE.nameLabel, SAVE.who, SAVE.when, SAVE.note]);
    expect(skillNameField(rig.el).value).toBe(DEFAULT_NAME);
    expect(SAVE.scopes.map((s) => isOn(choice(rig.el, s)))).toEqual([false, true]);
    expect(SAVE.triggers.map((s) => isOn(choice(rig.el, s)))).toEqual([false, false, true]);
    expect(textOf(qa(rig.el, "b").find((b) => textOf(b) === "Learning") as HTMLElement)).toBe(
      "Learning",
    );
    expect(await artIn(teachCard(rig.el))).toContain(
      await agentArt({ role: "builder", rank: "lead", expr: "talking" }, 40),
    );
  });

  it("WEB_8a_skills_teach_the_scope_and_trigger_pickers_each_hold_one_choice", async () => {
    const rig = await mountSkills();
    toSave(rig);
    clickEl(choice(rig.el, "Just me"));
    expect(SAVE.scopes.map((s) => isOn(choice(rig.el, s)))).toEqual([true, false]);
    clickEl(choice(rig.el, "Weekdays 09:00"));
    expect(SAVE.triggers.map((s) => isOn(choice(rig.el, s)))).toEqual([false, true, false]);
    clickEl(choice(rig.el, "When I ask"));
    expect(SAVE.triggers.map((s) => isOn(choice(rig.el, s)))).toEqual([true, false, false]);
  });

  it("WEB_8a_skills_teach_Save_skill_calls_saveSkill_once_with_the_draft_made_a_learning_skill", async () => {
    const rig = await mountSkills();
    const api = rig.api as ReturnType<typeof skillsApi>;
    toSave(rig);
    tap(rig, "Save skill");
    expect(api.saveSkill).toHaveBeenCalledTimes(1);
    expect(api.saveSkill.mock.calls[0]?.[0]).toEqual({
      ...log,
      ...SAVED_OVERRIDE,
      name: DEFAULT_NAME,
      draft: expect.objectContaining({ scope: "team", trigger: "arrive" }), // SKILLS-3: what a live save posts
    });
  });

  it("WEB_8a_skills_teach_the_name_typed_in_step_1_is_the_one_saved_shown_and_announced", async () => {
    const rig = await mountSkills();
    const api = rig.api as ReturnType<typeof skillsApi>;
    typeInto(skillNameField(rig.el), "Pay Northline");
    toSave(rig);
    expect(skillNameField(rig.el).value).toBe("Pay Northline");
    typeInto(skillNameField(rig.el), "Pay Northline early");
    tap(rig, "Save skill");
    expect(api.saveSkill.mock.calls[0]?.[0]).toMatchObject({
      id: "log",
      name: "Pay Northline early",
    });
    expect(card(rig)).toContain(savedTitle("Pay Northline early"));
    expect(toasts(rig.app)[0]?.[0]).toBe(savedToast("Pay Northline early", "Northwind Ops"));
  });

  it("WEB_8a_skills_teach_saving_toasts_once_with_no_action_and_shows_the_saved_banner", async () => {
    const rig = await mountSkills();
    toSave(rig);
    tap(rig, "Save skill");
    expect(toasts(rig.app)).toHaveLength(1);
    expect(toasts(rig.app)[0]?.[0]).toBe(
      "Saved “Log new supplier invoices”. It’s live for the team",
    );
    expect(toasts(rig.app)[0]?.[1]).toBeUndefined();
    showsAll(rig, [
      savedTitle(DEFAULT_NAME),
      savedLine("Northwind Ops", "When an invoice arrives"),
    ]);
    expect(hasControl(rig.el, "View in library")).toBe(true);
    expect(hasControl(rig.el, "Teach another")).toBe(true);
    expect(hasControl(rig.el, "Save skill")).toBe(false);
    expect(await artIn(teachCard(rig.el))).toContain(
      await agentArt({ role: "builder", rank: "lead", expr: "delighted" }, 70),
    );
  });

  it.each(
    SAVE.scopes.flatMap((scope) => SAVE.triggers.map((trig) => [scope, trig] as [Scope, Trigger])),
  )(
    "WEB_8a_skills_teach_saved_for_%s_runs_%s_says_so_in_the_line_and_the_toast",
    async (scope, trig) => {
      const rig = await mountSkills();
      toSave(rig);
      clickEl(choice(rig.el, scope));
      clickEl(choice(rig.el, trig));
      tap(rig, "Save skill");
      expect(card(rig)).toContain(savedLine(scope, trig));
      expect(toasts(rig.app)[0]?.[0]).toBe(savedToast(DEFAULT_NAME, scope));
    },
  );

  it("WEB_8a_skills_teach_a_blank_name_is_not_saved", async () => {
    // The design is silent; a skill with no name cannot be told apart in the library (see the WEB-8a report).
    const rig = await mountSkills();
    const api = rig.api as ReturnType<typeof skillsApi>;
    toSave(rig);
    typeInto(skillNameField(rig.el), "   ");
    clickEl(control(rig.el, "Save skill"));
    expect(api.saveSkill).not.toHaveBeenCalled();
    expect(toasts(rig.app)).toEqual([]);
    expect(card(rig)).not.toContain("is now a skill");
    expect(currentStep(rig.el)).toBe("Save");
  });

  it("WEB_8a_skills_teach_once_saved_every_step_is_locked_and_no_timer_runs", async () => {
    const rig = await mountSkills();
    toSave(rig);
    tap(rig, "Save skill");
    expect(reachable(rig.el)).toEqual([false, false, false, false]);
    expect(rig.clock.live()).toHaveLength(0);
  });

  it("WEB_8a_skills_teach_View_in_library_goes_to_the_skills_page_for_the_new_skill", async () => {
    const rig = await mountSkills();
    toSave(rig);
    tap(rig, "Save skill");
    expect(goCalls(rig.app)).toEqual([]);
    tap(rig, "View in library");
    expect(goCalls(rig.app)).toEqual([["skills", { id: "log" }]]);
  });

  it("WEB_8a_skills_teach_Teach_another_starts_over_on_step_1_with_nothing_captured_and_the_example_name", async () => {
    const rig = await mountSkills();
    typeInto(skillNameField(rig.el), "Pay Northline");
    toSave(rig);
    tap(rig, "Save skill");
    tap(rig, "Teach another");
    expect(currentStep(rig.el)).toBe("Show it");
    expect(pickedCount(rig.el)).toBe(0);
    expect(skillNameField(rig.el).value).toBe(DEFAULT_NAME);
    expect(card(rig)).not.toContain("is now a skill");
    expect(reachable(rig.el)).toEqual([true, false, false, false]);
    expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(true);
  });

  it("WEB_8a_skills_teach_Teach_a_skill_in_the_header_starts_over_after_a_save_and_only_scrolls_before_one", async () => {
    const scrollTo = vi.fn();
    const scrollIntoView = vi.fn();
    Object.defineProperty(window, "scrollTo", { value: scrollTo, configurable: true });
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      value: scrollIntoView,
      configurable: true,
    });
    const rig = await mountSkills();
    captureByDescribing(rig);
    clickEl(control(rig.el, "Teach a skill"));
    expect(scrollTo.mock.calls.length + scrollIntoView.mock.calls.length).toBeGreaterThan(0);
    expect(pickedCount(rig.el)).toBe(4); // a press before a save leaves the flow as it is
    expect(currentStep(rig.el)).toBe("Show it");
    toSave(rig);
    tap(rig, "Save skill");
    clickEl(control(rig.el, "Teach a skill"));
    expect(currentStep(rig.el)).toBe("Show it");
    expect(pickedCount(rig.el)).toBe(0);
  });

  it("WEB_8a_skills_teach_after_saving_the_header_counts_one_more_learning_skill_and_the_total_is_unchanged", async () => {
    const rig = await mountSkills();
    expect(elWithText(rig.el, "2 learning")).toBeDefined();
    toSave(rig);
    tap(rig, "Save skill");
    expect(elWithText(rig.el, "3 learning")).toBeDefined();
    expect(elWithText(rig.el, "4 trusted")).toBeDefined();
    expect(elWithText(rig.el, "6 need your help")).toBeDefined();
    expect(pageText(rig.el)).toContain("8 skills");
  });

  it("WEB_8a_skills_teach_saving_touches_nothing_else_it_does_not_approve_or_start_a_world", async () => {
    const rig = await mountSkills();
    toSave(rig);
    tap(rig, "Save skill");
    expect((rig.app.decide as unknown as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(0);
    expect((rig.app.addWorld as unknown as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(0);
  });

  it("WEB_8a_skills_teach_a_save_the_Api_cannot_take_does_not_crash_the_page", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const rig = await mountSkills({ api: skillsApi({ saveSkill: rejects }) });
    toSave(rig);
    tap(rig, "Save skill");
    await settle(); // an unhandled rejection would fail the run here
    expect(rig.el.isConnected).toBe(true);
    expect(qa(rig.el, "h1")).toHaveLength(1);
    expect(error).not.toHaveBeenCalled();
  });
});

describe("WEB_8a_skills_teach: keyboard and roles", () => {
  it("WEB_8a_skills_teach_every_control_of_the_flow_is_a_real_button_or_field_in_every_step", async () => {
    const rig = await mountSkills();
    const seen = new Set<string>();
    const sweep = () => {
      for (const b of qa(rig.el, "button")) {
        expect(b.tagName, textOf(b)).toBe("BUTTON");
        expect(b.getAttribute("type"), textOf(b)).toBe("button");
        expect(b.getAttribute("tabindex") ?? "0", textOf(b)).not.toMatch(/^[1-9]/);
        seen.add(textOf(b));
      }
    };
    sweep();
    toTilosVersion(rig);
    sweep();
    tap(rig, "Let Tilo try it");
    rig.clock.advance(3 * 900);
    sweep();
    tap(rig, TRY.yes);
    rig.clock.advance(900);
    sweep();
    tap(rig, "Looks right");
    sweep();
    tap(rig, "Save skill");
    sweep();
    for (const label of [
      "Teach a skill",
      "Show me Tilo’s version",
      "Let Tilo try it",
      TRY.yes,
      "Looks right",
      "Save skill",
      "View in library",
      "Teach another",
    ]) {
      expect(seen.has(label), label).toBe(true);
    }
  });

  it("WEB_8a_skills_teach_Enter_and_Space_press_a_method_tile_and_Enter_a_step", async () => {
    const rig = await mountSkills();
    press(methodTile(rig.el, "Describe it"), "Enter");
    expect(isOn(methodTile(rig.el, "Describe it"))).toBe(true);
    press(methodTile(rig.el, "Upload an example"), " ");
    expect(isOn(methodTile(rig.el, "Upload an example"))).toBe(true);
    press(dropzone(rig.el), "Enter");
    expect(pickedCount(rig.el)).toBe(4);
    press(stepButton(rig.el, "Tilo’s version"), "Enter");
    expect(currentStep(rig.el)).toBe("Tilo’s version");
  });

  it(
    "WEB_8a_skills_teach_exactly_one_step_is_current_after_any_sequence_of_presses",
    { timeout: 60_000 },
    async () => {
      // A seeded random walk over the card's controls: the invariants hold whatever order things are done in.
      const labels = [
        "Start recording",
        "Start walkthrough",
        "Record again",
        "Read my description",
        "Show me Tilo’s version",
        "Let Tilo try it",
        TRY.yes,
        "Fix a step",
        "Looks right",
        "Back",
        "Save skill",
        "Teach another",
      ];
      for (const seed of [3, 11, 29, 47, 101]) {
        let s = seed;
        const rnd = (n: number) => {
          s = (s * 1103515245 + 12345) % 2147483648;
          return s % n;
        };
        const rig = await mountSkills();
        for (let i = 0; i < 40; i++) {
          const op = rnd(6);
          if (op === 0)
            clickEl(methodTile(rig.el, (METHODS[rnd(4)] as (typeof METHODS)[number]).name));
          else if (op === 1) rig.clock.advance(rnd(2500));
          else if (op === 2) {
            const sw = askSwitches(rig.el);
            if (sw.length) clickEl(sw[rnd(sw.length)] as HTMLElement);
          } else if (op === 3) {
            const steps = reachable(rig.el);
            const open = steps.map((ok, k) => (ok ? k : -1)).filter((k) => k >= 0);
            const k = open[rnd(open.length)];
            if (k !== undefined) clickEl(stepBarButton(rig, k));
          } else {
            const present = labels.filter((l) => hasControl(rig.el, l));
            const l = present[rnd(present.length)];
            if (l) {
              const b = control(rig.el, l);
              if (!isDisabled(b)) clickEl(b);
            }
          }
          expect(
            qa(teachCard(rig.el), '[aria-current="step"]'),
            `seed ${seed} op ${i}`,
          ).toHaveLength(1);
          const stage = currentStep(rig.el);
          if (stage === "Show it") {
            const n = pickedCount(rig.el);
            expect(n).not.toBeNull();
            expect(n as number).toBeLessThanOrEqual(4);
            expect(isDisabled(control(rig.el, "Show me Tilo’s version"))).toBe(n !== 4);
          }
          if (stage === "Try run") {
            const st = runStatuses(rig.el);
            const first = st.findIndex((x) => x !== "Done");
            if (first >= 0) expect(st.slice(first + 1).every((x) => x === "Waiting")).toBe(true);
            expect(
              st.filter((x) => x === "Working…" || x === "Asking you").length,
            ).toBeLessThanOrEqual(1);
          }
        }
        cleanup();
      }
    },
  );
});

function stepBarButton(rig: SkillsRig, index: number): HTMLElement {
  return stepButton(rig.el, STEP_LABELS[index] as string);
}
