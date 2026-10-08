// @vitest-environment happy-dom
// ONBOARD-1 (user-requested, no PRD requirement; BQ-ONBOARD-1): the first-run welcome and the guided tour over the
// REAL Park nav (mounted through <AppShell/>). Honesty: nothing here says a run happened, and nothing moves.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  active,
  cleanup,
  click,
  countPrimary,
  press,
  q,
  qa,
} from "../../test-support/park/componentsHarness";
import { mountShell, settle } from "../../test-support/park/shellHarness";
import { AppShell } from "../park/shell/AppShell";
import { setParkTour } from "../park/shell/tour";
import { OnboardingLayer } from "./OnboardingLayer";
import { COPY } from "./steps";
import { requestTour } from "./tourEvents";

vi.mock("../park/engines/park", async () =>
  (await import("../../test-support/park/shellEngine")).parkMock(),
);

const KEY = "u-test";
const SEEN = `tilo.onboarding.v1.${KEY}`;

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  setParkTour(null);
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.pushState({}, "", "/");
});

interface Opts {
  enabled?: boolean | undefined;
  userKey?: string;
  findSample?: () => Promise<string | null>;
  withSeam?: boolean;
}

async function mountTour(o: Opts = {}) {
  const layer = (
    <OnboardingLayer
      {...(o.enabled === undefined ? {} : { enabled: o.enabled })}
      userKey={o.userKey ?? KEY}
      findSample={o.findSample ?? (async () => null)}
    />
  );
  const page = (
    <AppShell>
      <input aria-label="Describe your task" type="text" />
    </AppShell>
  );
  if (o.withSeam) setParkTour({ Layer: () => null, start: requestTour });
  const ui = (
    <>
      {page}
      {layer}
    </>
  );
  const r = mountShell(ui, { path: "/" });
  await settle();
  return r;
}

const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]');
const titleOf = (d: HTMLElement) => d.querySelector("h2")?.textContent ?? "";
const button = (name: string) =>
  qa<HTMLButtonElement>(document.body, "button").find((b) => (b.textContent ?? "").trim() === name);
const btn = (name: string): HTMLButtonElement => {
  const b = button(name);
  if (!b) throw new Error(`no button ${name}`);
  return b;
};
const status = () => document.querySelector('[role="status"][data-onboarding]')?.textContent ?? "";
const key = (k: string, el: Element = document.body) =>
  act(() => {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
  });

async function startTour(o: Opts = {}) {
  const r = await mountTour({ enabled: true, ...o });
  click(btn("Take the tour"));
  await settle();
  return r;
}

describe("ONBOARD_1 welcome", () => {
  it("ONBOARD_1_welcome_shows_once", async () => {
    await mountTour({ enabled: true });
    const d = dialog();
    expect(d).not.toBeNull();
    expect(d?.getAttribute("aria-modal")).toBe("true");
    expect(titleOf(d as HTMLElement)).toBe(COPY.welcomeTitle);
    expect(window.localStorage.getItem(SEEN)).not.toBeNull();
    cleanup();
    await mountTour({ enabled: true });
    expect(dialog()).toBeNull();
    cleanup();
    await mountTour({ enabled: true, userKey: "someone-else" });
    expect(dialog(), "another person still gets it").not.toBeNull();
  });

  it("ONBOARD_1_welcome_says_describe_plan_run_approve_in_three_steps", async () => {
    await mountTour({ enabled: true });
    const d = dialog() as HTMLElement;
    const items = qa(d, "ol > li");
    expect(items).toHaveLength(3);
    expect(items[0]?.textContent?.toLowerCase()).toContain("describe");
    expect(items[1]?.textContent?.toLowerCase()).toContain("director");
    expect(items[2]?.textContent?.toLowerCase()).toContain("approve");
    expect(d.getAttribute("aria-labelledby")).toBeTruthy();
    expect(d.getAttribute("aria-describedby")).toBeTruthy();
  });

  it("ONBOARD_1_welcome_has_one_filled_primary_button_UX1", async () => {
    await mountTour({ enabled: true });
    expect(countPrimary(document.body)).toBe(1);
    expect(button("Take the tour")?.className).toContain("park-btn--primary");
    expect(button("Skip for now")?.className).toContain("park-btn--secondary");
  });

  it("ONBOARD_1_welcome_automation_and_tests_do_not_auto_show", async () => {
    await mountTour();
    expect(dialog(), "unit tests (MODE=test) never see the first-run welcome").toBeNull();
  });

  it("ONBOARD_1_welcome_skip_and_esc_close_it_and_it_stays_seen", async () => {
    await mountTour({ enabled: true });
    click(btn("Skip for now"));
    expect(dialog()).toBeNull();
    cleanup();
    await mountTour({ enabled: true, userKey: "esc" });
    expect(dialog()).not.toBeNull();
    key("Escape");
    expect(dialog()).toBeNull();
  });

  it("ONBOARD_1_welcome_focus_moves_in_and_tab_stays_inside", async () => {
    await mountTour({ enabled: true });
    const d = dialog() as HTMLElement;
    expect(d.contains(active())).toBe(true);
    const take = btn("Take the tour");
    const skip = btn("Skip for now");
    skip.focus();
    key("Tab", skip); // from the last control: wraps to the first
    expect(active()).toBe(take);
    key("Tab", take);
    // shift+Tab from the first wraps to the last
    act(() => {
      take.focus();
      take.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Tab",
          shiftKey: true,
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    expect(active()).toBe(skip);
  });
});

describe("ONBOARD_1 tour", () => {
  it("ONBOARD_1_tour_steps_target_real_nav", async () => {
    await startTour();
    const d = dialog() as HTMLElement;
    const seenTitles: string[] = [];
    const expected: [string, () => Element | null][] = [
      ["Describe the work", () => document.querySelector('input[aria-label="Describe your task"]')],
      ["Worlds", () => document.querySelector('nav[aria-label="Main"] a[href="/worlds"]')],
      ["Skills", () => document.querySelector('nav[aria-label="Main"] a[href="/skills"]')],
      ["Ledger", () => document.querySelector('nav[aria-label="Main"] a[href="/ledger"]')],
      ["Agenda", () => document.querySelector('nav[aria-label="Main"] a[href="/agenda"]')],
      ["Team", () => document.querySelector('nav[aria-label="Main"] a[href="/team"]')],
      ["Notifications", () => document.querySelector('button[aria-label="Notifications"]')],
      ["Account menu", () => document.querySelector('button[aria-label="Account menu"]')],
    ];
    for (const [i, [title, target]] of expected.entries()) {
      const now = dialog() as HTMLElement;
      expect(titleOf(now)).toBe(title);
      seenTitles.push(titleOf(now));
      const el = target();
      expect(el, `${title}: the real element exists`).not.toBeNull();
      // The target is tied to the explanation for assistive technology, and is the highlighted one.
      const bodyId = now.getAttribute("aria-describedby") ?? "";
      expect(el?.getAttribute("aria-describedby")?.split(" ")).toContain(bodyId);
      expect(now.getAttribute("aria-labelledby")).toBeTruthy();
      expect(now.textContent).toContain(`Step ${i + 1} of ${expected.length}`);
      if (i < expected.length - 1) click(btn("Next"));
    }
    expect(seenTitles).toHaveLength(8);
    expect(d.isConnected || dialog() !== null).toBe(true);
  });

  it("ONBOARD_1_tour_target_description_is_restored_when_the_step_changes_and_on_close", async () => {
    await startTour();
    const input = document.querySelector('input[aria-label="Describe your task"]') as HTMLElement;
    expect(input.getAttribute("aria-describedby")).toBeTruthy();
    click(btn("Next"));
    expect(input.hasAttribute("aria-describedby")).toBe(false);
    click(btn("Skip tour"));
    for (const el of qa(document.body, "[aria-describedby]")) {
      expect(el.getAttribute("aria-describedby")).not.toMatch(/onb/);
    }
  });

  it("ONBOARD_1_tour_announces_each_step_politely", async () => {
    await startTour();
    const live = document.querySelector('[role="status"][data-onboarding]') as HTMLElement;
    expect(live.getAttribute("aria-live")).toBe("polite");
    expect(status()).toBe("Step 1 of 8: Describe the work");
    click(btn("Next"));
    expect(status()).toBe("Step 2 of 8: Worlds");
  });

  it("ONBOARD_1_tour_back_next_arrows_and_done", async () => {
    await startTour();
    expect(button("Back"), "no Back on the first step").toBeUndefined();
    const d = () => dialog() as HTMLElement;
    key("ArrowRight", d());
    expect(titleOf(d())).toBe("Worlds");
    key("ArrowLeft", d());
    expect(titleOf(d())).toBe("Describe the work");
    for (let i = 0; i < 7; i++) click(btn("Next"));
    expect(titleOf(d())).toBe("Account menu");
    expect(button("Next")).toBeUndefined();
    click(btn("Done"));
    expect(dialog()).toBeNull();
  });

  it("ONBOARD_1_tour_uses_no_filled_primary_so_the_screen_keeps_its_own_UX1", async () => {
    await startTour();
    expect(countPrimary(dialog() as HTMLElement)).toBe(0);
  });

  it("ONBOARD_1_skip_and_esc", async () => {
    await startTour();
    click(btn("Skip tour"));
    expect(dialog()).toBeNull();
    cleanup();
    window.localStorage.clear();
    await startTour();
    key("Escape");
    expect(dialog()).toBeNull();
    expect(button("Next")).toBeUndefined();
  });

  it("ONBOARD_1_tour_focus_moves_in_and_returns_to_where_it_was", async () => {
    await mountTour({ enabled: false, withSeam: true });
    const avatar = q<HTMLButtonElement>(document.body, 'button[aria-label="Account menu"]');
    act(() => avatar.focus());
    act(() => requestTour());
    await settle();
    expect((dialog() as HTMLElement).contains(active())).toBe(true);
    key("Escape");
    expect(active()).toBe(avatar);
  });

  it("ONBOARD_1_tour_tab_wraps_inside_the_coach_mark", async () => {
    await startTour();
    const d = dialog() as HTMLElement;
    const items = qa<HTMLElement>(d, "button");
    const last = items[items.length - 1] as HTMLElement;
    act(() => last.focus());
    key("Tab", last);
    expect(active()).toBe(items[0]);
  });
});

describe("ONBOARD_1 storage and replay", () => {
  it("ONBOARD_1_storage_throwing_still_renders", async () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    await mountTour({ enabled: true });
    expect(dialog()).not.toBeNull();
    click(btn("Take the tour"));
    await settle();
    expect(titleOf(dialog() as HTMLElement)).toBe("Describe the work");
    click(btn("Skip tour"));
    expect(dialog()).toBeNull();
  });

  it("ONBOARD_1_replay_from_account_menu", async () => {
    window.localStorage.setItem(SEEN, "seen");
    await mountTour({ enabled: true, withSeam: true });
    expect(dialog()).toBeNull();
    click(q(document.body, 'button[aria-label="Account menu"]'));
    const row = qa<HTMLButtonElement>(document.body, '[role="menuitem"]').find((b) =>
      b.textContent?.startsWith("Take the tour"),
    );
    expect(row, "the account menu has Take the tour").toBeDefined();
    click(row as HTMLButtonElement);
    await settle();
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(titleOf(dialog() as HTMLElement)).toBe("Describe the work");
    expect((dialog() as HTMLElement).contains(active())).toBe(true);
    click(btn("Skip tour"));
    expect(active()?.getAttribute("aria-label")).toBe("Account menu");
  });

  it("ONBOARD_1_replay_item_is_absent_without_the_tour_seam", async () => {
    await mountTour({ enabled: false });
    click(q(document.body, 'button[aria-label="Account menu"]'));
    const labels = qa(document.body, '[role="menuitem"]').map((b) => b.textContent ?? "");
    expect(labels.some((t) => t.startsWith("Take the tour"))).toBe(false);
  });
});

describe("ONBOARD_1 optional sample project step", () => {
  const SAMPLE = "w_sample_village_basic";

  it("ONBOARD_1_sample_step_offered_when_the_worlds_list_marks_one", async () => {
    const { navigate } = await startTour({ findSample: async () => SAMPLE });
    for (let i = 0; i < 7; i++) click(btn("Next"));
    click(btn("Next")); // Account menu -> sample step
    const d = dialog() as HTMLElement;
    expect(titleOf(d)).toBe("A sample project");
    expect(d.textContent).toContain("Step 9 of 9");
    click(btn("Open the sample project"));
    expect(navigate).toHaveBeenCalledWith(`/world/${SAMPLE}`);
    expect(dialog()).toBeNull();
  });

  it("ONBOARD_1_sample_step_omitted_when_the_list_has_no_sample", async () => {
    await startTour({ findSample: async () => null });
    for (let i = 0; i < 7; i++) click(btn("Next"));
    expect(titleOf(dialog() as HTMLElement)).toBe("Account menu");
    expect(button("Next")).toBeUndefined();
    expect(dialog()?.textContent).toContain("Step 8 of 8");
    expect(button("Open the sample project")).toBeUndefined();
  });

  it("ONBOARD_1_sample_step_omitted_when_the_call_fails", async () => {
    await startTour({
      findSample: () => Promise.reject(new Error("offline")),
    });
    for (let i = 0; i < 7; i++) click(btn("Next"));
    expect(dialog()?.textContent).toContain("Step 8 of 8");
    expect(button("Open the sample project")).toBeUndefined();
  });
});

describe("ONBOARD_1 reduced motion and honesty", () => {
  it("ONBOARD_1_reduced_motion_nothing_moves_so_nothing_to_turn_off", () => {
    const dir = join(__dirname);
    const css = readFileSync(join(dir, "onboarding.css"), "utf8");
    expect(css).not.toMatch(/\btransition\b|\banimation\b|@keyframes|scroll-behavior/);
    for (const f of ["OnboardingLayer.tsx", "CoachMark.tsx", "Welcome.tsx"]) {
      const src = readFileSync(join(dir, f), "utf8");
      expect(src, f).not.toMatch(
        /requestAnimationFrame|setInterval|setTimeout|\.animate\s*\(|behavior\s*:\s*["']smooth/,
      );
    }
  });

  it("ONBOARD_1_no_run_claims", () => {
    const text = JSON.stringify(COPY).toLowerCase();
    const claims =
      /\b(ran|running|has run|have run|finished|completed|in progress|working now|just now|live now|streak|hurry|don't miss|last chance)\b/;
    expect(text).not.toMatch(claims);
    expect(text).not.toMatch(/\d+\s*(agents|runs|worlds)/);
  });

  it("ONBOARD_1_every_step_has_plain_english_copy", () => {
    expect(COPY.tour.length).toBeGreaterThanOrEqual(8);
    for (const s of COPY.tour) {
      expect(s.title.length).toBeGreaterThan(2);
      expect(s.body.length).toBeGreaterThan(20);
    }
  });
});
