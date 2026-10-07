// @vitest-environment happy-dom
// WEB-3b: the world loader and the boot splash (README "Interactions and motion": Open a world, Boot;
// reference `Tilo App.dc.html`: wl and boot). Both are STATIC here: the spinner is a ring, the bar jumps to
// its width, the card and the splash are removed at once (no fade; the motion restore is BQ-WEB-3).
// The loader is reached through <AppShell/> and `store.openWorld(id)`; the splash through <BootSplash ready/>
// (the one prop the brief names). Copy, steps and widths are the reference's:
//   - role="status" aria-live="polite" scrim; eyebrow "OPENING <TIER>", the world name, "<tool> · <n> agent(s)";
//   - three steps per tier (City: "Loading districts and buildings", "Waking <n> agents", "Syncing spend and
//     decisions"; Town: "Loading the routine", "Reading run history", "Checking the next run"; Village:
//     "Loading the task", "Checking progress", "Fetching results"); a step before the current one is done
//     (a check svg before its label), the others are not;
//   - the bar's width is min(100, (step + 1) * 30)%, set inline: 30%, 60%, 90%, 100%.
import { act, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { fakeScheduler } from "../../../test-support/park/appHarness";
import { cleanup, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp, mountShell, seen } from "../../../test-support/park/shellHarness";
import { BootSplash } from "./BootSplash";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const loader = () =>
  qa(document.body, '[role="status"]').find((e) => (e.textContent ?? "").includes("OPENING")) ??
  null;
/** The browser's own "the fade has finished" (WEB-MOTION-2: the card and the splash fade out, then go). */
const animationEnd = (el: Element | null) =>
  act(() => {
    el?.dispatchEvent(new Event("animationend", { bubbles: true }));
  });
const labelEl = (root: HTMLElement, label: string): Element => {
  const hits = qa(root, "*").filter((e) => (e.textContent ?? "").trim() === label);
  const deepest = hits[hits.length - 1];
  if (!deepest) throw new Error(`no step reads "${label}"`);
  return deepest;
};
/** How many ticks (svg) come before each step label, in document order. */
const ticksBefore = (labels: readonly string[]): number[] => {
  const root = loader() as HTMLElement;
  const ticks = qa(root, "svg");
  return labels.map((l) => {
    const el = labelEl(root, l);
    // a check counts for a step when it sits before the label, or inside the step's own row (check first)
    return ticks.filter(
      (t) => el.contains(t) || t.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).length;
  });
};
const widths = () =>
  qa(loader() as HTMLElement, "[style]")
    .map((e) => e.style.width)
    .filter((w) => w.endsWith("%"));
const open = (id: string) => act(() => seen.store.openWorld(id));
const tick = (sch: ReturnType<typeof fakeScheduler>, n = 1) => {
  for (let i = 0; i < n; i++) act(() => sch.fire(sch.live()[0]));
};

const CITY = ["Loading districts and buildings", "Waking 38 agents", "Syncing spend and decisions"];

describe("WEB_3b_loader: the card", () => {
  it("WEB_3b_loader_nothing_shows_until_a_world_is_opened", async () => {
    await mountApp();
    expect(loader()).toBeNull();
  });

  it("WEB_3b_loader_it_is_a_polite_status_and_a_scrim_over_the_page", async () => {
    await mountApp();
    open("k1");
    const el = loader() as HTMLElement;
    expect(el.getAttribute("role")).toBe("status");
    expect(el.getAttribute("aria-live")).toBe("polite");
  });

  it("WEB_3b_loader_a_city_shows_art_OPENING_CITY_name_meta_and_its_three_steps", async () => {
    await mountApp();
    open("k1");
    const el = loader() as HTMLElement;
    expect(el.querySelector("img, svg")).not.toBeNull(); // the world's art
    const text = el.textContent ?? "";
    for (const s of ["OPENING CITY", "K1 electric scooter", "Workspace · 38 agents", ...CITY]) {
      expect(text, s).toContain(s);
    }
    expect(text.indexOf("OPENING CITY")).toBeLessThan(text.indexOf("K1 electric scooter"));
    expect(text.indexOf("Workspace · 38 agents")).toBeLessThan(text.indexOf(CITY[0] as string));
  });

  it("WEB_3b_loader_a_town_says_OPENING_TOWN_with_the_routine_steps", async () => {
    await mountApp();
    open("invoice");
    const text = (loader() as HTMLElement).textContent ?? "";
    for (const s of [
      "OPENING TOWN",
      "Weekly invoice match",
      "Routine · 5 agents",
      "Loading the routine",
      "Reading run history",
      "Checking the next run",
    ]) {
      expect(text, s).toContain(s);
    }
    expect((loader() as HTMLElement).querySelector("img, svg")).not.toBeNull();
  });

  it("WEB_3b_loader_a_village_says_OPENING_VILLAGE_and_one_agent_is_singular", async () => {
    await mountApp();
    open("comp");
    const text = (loader() as HTMLElement).textContent ?? "";
    for (const s of [
      "OPENING VILLAGE",
      "Competitor pricing",
      "Quick task · 1 agent",
      "Loading the task",
      "Checking progress",
      "Fetching results",
    ]) {
      expect(text, s).toContain(s);
    }
    expect(text).not.toContain("1 agents");
  });

  it("WEB_3b_loader_two_agents_is_plural", async () => {
    await mountApp();
    open("venues");
    expect((loader() as HTMLElement).textContent).toContain("Quick task · 2 agents");
  });

  it("WEB_3b_loader_a_world_the_user_started_shows_its_own_name_and_tier", async () => {
    await mountApp();
    act(() => {
      seen.app.addWorld("routine", "Every Monday, match invoices");
    });
    open("new1");
    const text = (loader() as HTMLElement).textContent ?? "";
    expect(text).toContain("OPENING TOWN");
    expect(text).toContain("Every Monday, match invoices");
  });

  it("WEB_3b_loader_an_unknown_world_shows_no_card", async () => {
    await mountApp();
    open("nope");
    expect(loader()).toBeNull();
  });
});

describe("WEB_3b_loader: the steps tick and the bar widens, with no animation", () => {
  it("WEB_3b_loader_step_0_has_no_check_yet_and_the_bar_is_at_30_percent", async () => {
    await mountApp();
    open("k1");
    expect(ticksBefore(CITY)).toEqual([0, 0, 0]);
    expect(widths()).toEqual(["30%"]);
  });

  it("WEB_3b_loader_each_tick_checks_one_more_step_and_widens_the_bar_30_60_90_100", async () => {
    const { sch } = await mountApp();
    open("k1");
    tick(sch);
    expect(ticksBefore(CITY)).toEqual([1, 1, 1]); // step 0 done
    expect(widths()).toEqual(["60%"]);
    tick(sch);
    expect(ticksBefore(CITY)).toEqual([1, 2, 2]);
    expect(widths()).toEqual(["90%"]);
    tick(sch);
    expect(ticksBefore(CITY)).toEqual([1, 2, 3]); // all three done
    expect(widths()).toEqual(["100%"]);
  });

  it("WEB_3b_loader_the_page_swaps_at_step_3_while_the_card_is_still_there_and_goes_after", async () => {
    const { sch, navigate } = await mountApp();
    open("comp");
    tick(sch, 2);
    expect(navigate).not.toHaveBeenCalled();
    tick(sch);
    expect(navigate).toHaveBeenCalledWith("/park/world/comp");
    expect(loader()).not.toBeNull();
    tick(sch);
    // Updated for WEB-MOTION-2: the card now fades out over 280 ms after the last step, and goes at animationend.
    expect(loader()).not.toBeNull();
    animationEnd(loader());
    expect(loader()).toBeNull();
    expect(
      qa(document.body, "[role=status]").filter((e) => (e.textContent ?? "").includes("OPENING")),
    ).toHaveLength(0);
  });

  it("WEB_3b_loader_nothing_in_the_card_is_animated_or_transitioned", async () => {
    const { sch } = await mountApp();
    open("k1");
    for (let i = 0; i < 3; i++) {
      for (const el of qa(loader() as HTMLElement, "[style]")) {
        expect(el.getAttribute("style") ?? "").not.toMatch(/transition|animation/i);
      }
      tick(sch);
    }
  });

  it("WEB_3b_loader_opening_another_world_swaps_the_card_to_it_at_step_0", async () => {
    const { sch } = await mountApp();
    open("k1");
    tick(sch);
    open("comp");
    expect((loader() as HTMLElement).textContent).toContain("Competitor pricing");
    expect(widths()).toEqual(["30%"]);
  });
});

describe("WEB_3b_boot: the splash", () => {
  it("WEB_3b_boot_while_not_ready_it_is_a_status_named_Loading_Tilo_with_the_wordmark_and_text", () => {
    const { m } = mountShell(<BootSplash ready={false} />);
    const el = q(m.container, '[role="status"]');
    expect(el.getAttribute("aria-label")).toBe("Loading Tilo");
    expect(el.textContent).toContain("tilo");
    expect(el.textContent).toContain("Loading your city");
  });

  it("WEB_3b_boot_when_ready_it_renders_nothing", () => {
    const { m } = mountShell(<BootSplash ready />);
    expect(m.container.querySelector('[aria-label="Loading Tilo"]')).toBeNull();
    expect(m.container.textContent).not.toContain("Loading your city");
  });

  it("WEB_3b_boot_it_is_removed_the_moment_ready_turns_true", () => {
    let setReady: (v: boolean) => void = () => undefined;
    function Host() {
      const [ready, set] = useState(false);
      setReady = set;
      return <BootSplash ready={ready} />;
    }
    const { m } = mountShell(<Host />);
    expect(m.container.querySelector('[aria-label="Loading Tilo"]')).not.toBeNull();
    act(() => setReady(true));
    // Updated for WEB-MOTION-2: the splash fades over .45 s once ready, and goes at animationend.
    expect(m.container.querySelector('[aria-label="Loading Tilo"]')).not.toBeNull();
    animationEnd(m.container.querySelector('[aria-label="Loading Tilo"]'));
    expect(m.container.querySelector('[aria-label="Loading Tilo"]')).toBeNull();
  });

  it("WEB_3b_boot_nothing_in_it_is_animated", () => {
    const { m } = mountShell(<BootSplash ready={false} />);
    for (const el of qa(m.container, "[style]")) {
      expect(el.getAttribute("style") ?? "").not.toMatch(/transition|animation/i);
    }
  });

  it("WEB_3b_boot_the_shell_has_dropped_it_once_the_engines_are_built", async () => {
    await mountApp();
    // Updated for WEB-MOTION-2: it fades first (no longer a loading status), and goes at animationend.
    expect(document.querySelector('[role="status"][aria-label="Loading Tilo"]')).toBeNull();
    animationEnd(document.querySelector('[aria-label="Loading Tilo"]'));
    expect(document.querySelector('[aria-label="Loading Tilo"]')).toBeNull();
  });
});
