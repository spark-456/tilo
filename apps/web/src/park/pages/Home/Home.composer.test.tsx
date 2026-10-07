// @vitest-environment happy-dom
// WEB-4 acceptance: the composer (README "Home": "Composer flow: idle -> drafting (900ms) -> plan with cost
// and steps -> start. Starting calls addWorld() and toasts with an 'Open' action"; the reference's
// state { m, q, ph } and its handlers). The 900 ms is the injected scheduler's: the page asks
// `useSchedule()` (park/app/context.tsx, pinned in Home.schedule.test.tsx) and never calls setTimeout.
// Reference behaviours pinned on purpose: an empty or blank query is allowed and stands in with the mode's
// example task; the start control does nothing while drafting or planning; typing, a chip or a size change
// returns to idle and keeps the text; confirming clears the text and keeps the size.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, press, qa } from "../../../../test-support/park/componentsHarness";
import { MODES, QUICK, ROUTINE, WORKSPACE } from "../../../../test-support/park/homeCopy";
import {
  type HomeRig,
  clickEl,
  control,
  flat,
  hasControl,
  isSelected,
  mountHome,
  pageText,
  selectedSize,
  settle,
  sizeGroup,
  sizeOptions,
  taskInput,
  textOf,
  typeInto,
} from "../../../../test-support/park/homeHarness";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const DRAFT_MS = 900;
const drafting = (rig: HomeRig): HTMLElement | undefined =>
  qa(rig.el, '[role="status"]').find((e) => textOf(e).startsWith("Tilo is drafting"));
const draftTimers = (rig: HomeRig) => rig.sch.timers.filter((t) => t.ms === DRAFT_MS);
const liveDraft = (rig: HomeRig) => rig.sch.live().filter((t) => t.ms === DRAFT_MS);
const planSteps = (rig: HomeRig) => qa(rig.el, "ol > li").map((li) => flat(textOf(li)));
const chipsShown = (rig: HomeRig, labels: readonly string[]) =>
  labels.every((l) => hasControl(rig.el, l));

async function pick(rig: HomeRig, label: string): Promise<void> {
  const option = sizeOptions(rig.el).find((o) => textOf(o) === label);
  if (!option) throw new Error(`no size option ${label}`);
  clickEl(option);
  await settle();
}

async function start(rig: HomeRig, query?: string): Promise<void> {
  if (query !== undefined) typeInto(taskInput(rig.el), query);
  const label = MODES.map((m) => m.start).find((l) => hasControl(rig.el, l)) ?? "";
  clickEl(control(rig.el, label));
  await settle();
}

async function toPlan(rig: HomeRig, query?: string): Promise<void> {
  await start(rig, query);
  rig.sch.fire(liveDraft(rig)[0]);
  await settle();
}

describe("WEB_4_home_composer: idle", () => {
  it("WEB_4_home_composer_idle_shows_the_quick_task_composer", async () => {
    const rig = await mountHome();
    const input = taskInput(rig.el);
    expect(input.value).toBe("");
    expect(input.placeholder).toBe(`e.g. ${QUICK.example}`);
    expect(hasControl(rig.el, QUICK.start)).toBe(true);
    expect(pageText(rig.el)).toContain(QUICK.hint);
    expect(chipsShown(rig, QUICK.chips)).toBe(true);
    expect(sizeOptions(rig.el).map((o) => textOf(o))).toEqual(MODES.map((m) => m.label));
    expect(selectedSize(rig.el)).toBe("Quick task");
    expect(drafting(rig)).toBeUndefined();
    expect(qa(rig.el, "ol")).toHaveLength(0);
    expect(rig.sch.timers).toHaveLength(0); // nothing is scheduled until the person starts
  });

  it.each(MODES)(
    "WEB_4_home_composer_size_sets_start_placeholder_hint_and_chips_for_$label",
    async (mode) => {
      const rig = await mountHome();
      await pick(rig, mode.label);
      expect(selectedSize(rig.el)).toBe(mode.label);
      expect(taskInput(rig.el).placeholder).toBe(`e.g. ${mode.example}`);
      expect(hasControl(rig.el, mode.start)).toBe(true);
      expect(pageText(rig.el)).toContain(mode.hint);
      expect(chipsShown(rig, mode.chips)).toBe(true);
      const others = MODES.filter((m) => m !== mode);
      for (const o of others) {
        expect(hasControl(rig.el, o.start), `${o.start} is the other sizes'`).toBe(false);
        expect(pageText(rig.el)).not.toContain(o.hint);
      }
    },
  );

  it("WEB_4_home_composer_size_of_job_is_the_sliding_segmented_control", async () => {
    const rig = await mountHome();
    const group = sizeGroup(rig.el);
    expect(group.classList.contains("park-seg--sliding")).toBe(true);
    const thumb = group.querySelector<HTMLElement>(".park-seg__thumb");
    expect(thumb?.style.transform).toBe("translateX(0%)");
    await pick(rig, "Workspace");
    expect(group.querySelector<HTMLElement>(".park-seg__thumb")?.style.transform).toBe(
      "translateX(200%)",
    );
  });

  it("WEB_4_home_composer_arrow_keys_move_the_size_and_select_it", async () => {
    const rig = await mountHome();
    const [quick] = sizeOptions(rig.el);
    expect(quick && isSelected(quick)).toBe(true);
    if (quick) press(quick, "ArrowRight");
    await settle();
    expect(selectedSize(rig.el)).toBe("Routine");
    const routine = sizeOptions(rig.el)[1];
    if (routine) press(routine, "ArrowRight");
    await settle();
    expect(selectedSize(rig.el)).toBe("Workspace");
    expect(hasControl(rig.el, WORKSPACE.start)).toBe(true);
  });

  it("WEB_4_home_composer_a_size_change_keeps_what_was_typed", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Compare three suppliers");
    await pick(rig, "Routine");
    expect(taskInput(rig.el).value).toBe("Compare three suppliers");
  });

  it("WEB_4_home_composer_a_chip_fills_the_input_and_does_not_start", async () => {
    const rig = await mountHome();
    clickEl(control(rig.el, QUICK.chips[1] ?? ""));
    await settle();
    expect(taskInput(rig.el).value).toBe(QUICK.chips[1]);
    expect(drafting(rig)).toBeUndefined();
    expect(draftTimers(rig)).toHaveLength(0);
  });
});

describe("WEB_4_home_composer: drafting", () => {
  it("WEB_4_home_composer_start_goes_to_drafting_at_once_and_schedules_900_ms", async () => {
    const rig = await mountHome();
    await start(rig, "Compare three suppliers");
    const status = drafting(rig);
    expect(status, "role=status line while drafting").toBeTruthy();
    expect(textOf(status as HTMLElement)).toBe(
      "Tilo is drafting a village for “Compare three suppliers”",
    );
    expect(draftTimers(rig)).toHaveLength(1);
    expect(liveDraft(rig)).toHaveLength(1);
    expect(qa(rig.el, "ol")).toHaveLength(0); // no plan yet
    expect(chipsShown(rig, QUICK.chips), "chips are only for idle").toBe(false);
    expect(rig.app.addWorld).not.toHaveBeenCalled();
  });

  it.each(MODES)("WEB_4_home_composer_drafting_names_the_size_word_for_$label", async (mode) => {
    const rig = await mountHome();
    await pick(rig, mode.label);
    await start(rig, "Plan the offsite");
    expect(textOf(drafting(rig) as HTMLElement)).toBe(
      `Tilo is drafting a ${mode.word} for “Plan the offsite”`,
    );
  });

  it("WEB_4_home_composer_an_empty_query_drafts_with_the_example_task_in_its_place", async () => {
    const rig = await mountHome();
    await start(rig);
    expect(textOf(drafting(rig) as HTMLElement)).toBe(
      `Tilo is drafting a village for “${QUICK.example}”`,
    );
    cleanup();
    const blank = await mountHome();
    await start(blank, "   ");
    expect(textOf(drafting(blank) as HTMLElement)).toBe(
      `Tilo is drafting a village for “${QUICK.example}”`,
    );
  });

  it("WEB_4_home_composer_Enter_in_the_input_starts_and_other_keys_do_not", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Compare three suppliers");
    press(taskInput(rig.el), "a");
    press(taskInput(rig.el), "Tab");
    expect(drafting(rig)).toBeUndefined();
    press(taskInput(rig.el), "Enter");
    await settle();
    expect(drafting(rig)).toBeTruthy();
    expect(draftTimers(rig)).toHaveLength(1);
  });

  it("WEB_4_home_composer_starting_again_while_drafting_or_planning_does_nothing", async () => {
    const rig = await mountHome();
    await start(rig, "Compare three suppliers");
    clickEl(control(rig.el, QUICK.start));
    press(taskInput(rig.el), "Enter");
    await settle();
    expect(draftTimers(rig)).toHaveLength(1);
    rig.sch.fire(liveDraft(rig)[0]);
    await settle();
    clickEl(control(rig.el, QUICK.start));
    press(taskInput(rig.el), "Enter");
    await settle();
    expect(draftTimers(rig)).toHaveLength(1);
    expect(rig.app.addWorld).not.toHaveBeenCalled();
  });

  it("WEB_4_home_composer_editing_the_brief_while_drafting_cancels_the_draft", async () => {
    const rig = await mountHome();
    await start(rig, "Compare three suppliers");
    typeInto(taskInput(rig.el), "Compare four suppliers");
    await settle();
    for (const t of rig.sch.live()) rig.sch.fire(t); // whatever is still pending runs now
    await settle();
    expect(
      qa(rig.el, "ol"),
      "an old draft must not open a plan for text that changed",
    ).toHaveLength(0);
    expect(drafting(rig)).toBeUndefined();
    expect(taskInput(rig.el).value).toBe("Compare four suppliers");
  });

  it("WEB_4_home_composer_leaving_the_page_cancels_the_pending_draft", async () => {
    const rig = await mountHome();
    await start(rig, "Compare three suppliers");
    expect(liveDraft(rig)).toHaveLength(1);
    rig.m.unmount();
    expect(liveDraft(rig), "no timer outlives the page").toHaveLength(0);
  });
});

describe("WEB_4_home_composer: the plan", () => {
  it.each(MODES)("WEB_4_home_composer_plan_shows_tier_cost_and_steps_for_$label", async (mode) => {
    const rig = await mountHome();
    await pick(rig, mode.label);
    await toPlan(rig, "Plan the offsite");
    expect(drafting(rig)).toBeUndefined();
    const text = pageText(rig.el);
    expect(text.toUpperCase()).toContain(mode.tier); // the reference shows the tier in capitals
    expect(text).toContain("Plan the offsite");
    expect(flat(text)).toContain(flat(`Agents ${mode.agents}`));
    expect(flat(text)).toContain(flat(`Cost ${mode.cost}`));
    expect(flat(text)).toContain(flat(`Time ${mode.eta}`));
    expect(planSteps(rig)).toEqual(mode.steps.map((s, i) => flat(`${i + 1}${s}`)));
    expect(hasControl(rig.el, mode.confirm)).toBe(true);
    expect(hasControl(rig.el, "Change brief")).toBe(true);
    expect(chipsShown(rig, mode.chips), "chips are only for idle").toBe(false);
    expect(rig.app.addWorld).not.toHaveBeenCalled(); // nothing starts before the person confirms
  });

  it("WEB_4_home_composer_the_plan_tier_badge_reads_VILLAGE_TOWN_CITY", async () => {
    const rig = await mountHome();
    for (const mode of MODES) {
      await pick(rig, mode.label);
      await toPlan(rig, "x");
      const badge = qa(rig.el, "span, div").find(
        (e) => textOf(e).toLowerCase() === mode.tier.toLowerCase(),
      );
      expect(badge, mode.tier).toBeTruthy();
      clickEl(control(rig.el, "Change brief"));
      await settle();
    }
  });

  it("WEB_4_home_composer_Change_brief_returns_to_idle_and_keeps_the_text", async () => {
    const rig = await mountHome();
    await toPlan(rig, "Compare three suppliers");
    clickEl(control(rig.el, "Change brief"));
    await settle();
    expect(qa(rig.el, "ol")).toHaveLength(0);
    expect(taskInput(rig.el).value).toBe("Compare three suppliers");
    expect(chipsShown(rig, QUICK.chips)).toBe(true);
    expect(rig.app.addWorld).not.toHaveBeenCalled();
    await start(rig); // and the person can start again
    expect(draftTimers(rig)).toHaveLength(2);
  });

  it("WEB_4_home_composer_typing_in_the_plan_state_returns_to_idle", async () => {
    const rig = await mountHome();
    await toPlan(rig, "Compare three suppliers");
    typeInto(taskInput(rig.el), "Compare three suppliers now");
    await settle();
    expect(qa(rig.el, "ol")).toHaveLength(0);
    expect(hasControl(rig.el, "Change brief")).toBe(false);
    expect(chipsShown(rig, QUICK.chips)).toBe(true);
  });

  it("WEB_4_home_composer_a_size_change_in_the_plan_state_returns_to_idle_and_the_new_plan_differs", async () => {
    const rig = await mountHome();
    await toPlan(rig, "Compare three suppliers");
    expect(planSteps(rig)).toEqual(QUICK.steps.map((s, i) => flat(`${i + 1}${s}`)));
    await pick(rig, "Routine");
    expect(qa(rig.el, "ol")).toHaveLength(0);
    await toPlan(rig);
    expect(planSteps(rig)).toEqual(ROUTINE.steps.map((s, i) => flat(`${i + 1}${s}`)));
    expect(hasControl(rig.el, ROUTINE.confirm)).toBe(true);
    expect(taskInput(rig.el).value).toBe("Compare three suppliers");
  });
});

describe("WEB_4_home_composer: confirming", () => {
  it.each(MODES)(
    "WEB_4_home_composer_confirm_calls_addWorld_once_with_mode_and_text_for_$label",
    async (mode) => {
      const rig = await mountHome();
      await pick(rig, mode.label);
      await toPlan(rig, "  Plan the offsite  ");
      clickEl(control(rig.el, mode.confirm));
      await settle();
      expect(rig.app.addWorld).toHaveBeenCalledTimes(1);
      expect(rig.app.addWorld).toHaveBeenCalledWith(mode.key, "Plan the offsite");
      expect(
        rig.app.toast,
        "the toast is the store's, made inside addWorld",
      ).not.toHaveBeenCalled();
    },
  );

  it("WEB_4_home_composer_confirm_resets_to_idle_clears_the_text_and_keeps_the_size", async () => {
    const rig = await mountHome();
    await pick(rig, "Routine");
    await toPlan(rig, "Weekly invoice match");
    clickEl(control(rig.el, ROUTINE.confirm));
    await settle();
    expect(taskInput(rig.el).value).toBe("");
    expect(qa(rig.el, "ol")).toHaveLength(0);
    expect(drafting(rig)).toBeUndefined();
    expect(selectedSize(rig.el)).toBe("Routine");
    expect(hasControl(rig.el, ROUTINE.start)).toBe(true);
    expect(chipsShown(rig, ROUTINE.chips)).toBe(true);
  });

  it("WEB_4_home_composer_a_blank_query_confirms_with_an_empty_string_for_addWorld", async () => {
    const rig = await mountHome();
    await toPlan(rig, "   ");
    clickEl(control(rig.el, QUICK.confirm));
    await settle();
    expect(rig.app.addWorld).toHaveBeenCalledTimes(1);
    expect(rig.app.addWorld).toHaveBeenCalledWith("quick", "");
  });

  it("WEB_4_home_composer_the_whole_flow_works_from_the_keyboard", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Compare three suppliers");
    press(taskInput(rig.el), "Enter");
    await settle();
    rig.sch.fire(liveDraft(rig)[0]);
    await settle();
    press(control(rig.el, QUICK.confirm), "Enter"); // a real <button>: Enter activates it
    await settle();
    expect(rig.app.addWorld).toHaveBeenCalledWith("quick", "Compare three suppliers");
  });
});
