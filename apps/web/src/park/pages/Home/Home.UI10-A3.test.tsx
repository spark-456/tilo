// @vitest-environment happy-dom
// UI-10 / A3 (14 Oct QA, Home plan card): a 4,500-character unbroken task, no cap on the task box, Esc not closing
// the plan card, and "Change brief" dropping focus. The boxes (card not over the tiles) are in
// e2e/park-home-a3-plan-card.spec.ts.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, qa } from "../../../../test-support/park/componentsHarness";
import { QUICK } from "../../../../test-support/park/homeCopy";
import {
  type HomeRig,
  clickEl,
  control,
  mountHome,
  settle,
  taskInput,
  typeInto,
} from "../../../../test-support/park/homeHarness";
import { INTAKE_MAX_CHARS } from "./homeData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const DRAFT_MS = 900;
const card = (rig: HomeRig) => rig.el.querySelector(".park-home-plan");

async function toPlan(rig: HomeRig, text: string): Promise<void> {
  typeInto(taskInput(rig.el), text);
  clickEl(control(rig.el, QUICK.start));
  await settle();
  rig.sch.fire(rig.sch.live().filter((t) => t.ms === DRAFT_MS)[0]);
  await settle();
}

const pressEsc = (): void => {
  act(() => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  });
};

describe("UI_10_A3_home_plan_card", () => {
  it("UI_10_A3_the_task_box_takes_no_more_than_the_servers_intake_text_limit", async () => {
    const rig = await mountHome();
    expect(INTAKE_MAX_CHARS).toBe(4000);
    expect(taskInput(rig.el).maxLength).toBe(INTAKE_MAX_CHARS);
  });

  it("UI_10_A3_a_long_unbroken_task_shows_in_the_card_with_its_full_text_as_the_title", async () => {
    const rig = await mountHome();
    const long = "A".repeat(3000);
    await toPlan(rig, long);
    const query = rig.el.querySelector<HTMLElement>(".park-home-plan__query");
    expect(query?.getAttribute("title")).toBe(long);
    expect(query?.textContent).toBe(long);
  });

  it("UI_10_A3_Esc_closes_the_plan_card_and_returns_to_the_task_box", async () => {
    const rig = await mountHome();
    await toPlan(rig, "Compare three suppliers");
    expect(card(rig)).not.toBeNull();
    pressEsc();
    await settle();
    expect(card(rig)).toBeNull();
    expect(document.activeElement).toBe(taskInput(rig.el));
    expect(taskInput(rig.el).value).toBe("Compare three suppliers");
  });

  it("UI_10_A3_Esc_while_drafting_cancels_the_draft", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Compare three suppliers");
    clickEl(control(rig.el, QUICK.start));
    await settle();
    expect(qa(rig.el, '[role="status"]').length).toBeGreaterThan(0);
    pressEsc();
    await settle();
    expect(qa(rig.el, '[role="status"]')).toHaveLength(0);
    expect(rig.sch.live().filter((t) => t.ms === DRAFT_MS)).toHaveLength(0);
  });

  it("UI_10_A3_Change_brief_puts_the_focus_in_the_task_box", async () => {
    const rig = await mountHome();
    await toPlan(rig, "Compare three suppliers");
    clickEl(control(rig.el, "Change brief"));
    await settle();
    expect(card(rig)).toBeNull();
    expect(document.activeElement).toBe(taskInput(rig.el));
  });

  it("UI_10_A3_Esc_does_nothing_when_no_plan_is_open", async () => {
    const rig = await mountHome();
    typeInto(taskInput(rig.el), "Keep this");
    pressEsc();
    await settle();
    expect(taskInput(rig.el).value).toBe("Keep this");
  });
});
