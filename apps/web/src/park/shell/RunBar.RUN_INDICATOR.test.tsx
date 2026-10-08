// @vitest-environment happy-dom
// RUN-INDICATOR (PRD 9.4 HR-1, HR-2; no fake progress): the run bar at the bottom of the Park app. It reads the
// worlds the Api serves (the same recorded state the Worlds page shows) and shows ONLY while one of them is
// running; a held one reads a static "Waiting for your approval"; a terminal state removes it. On the fixture path
// only worlds the person started in this session count (the canned sample worlds are not runs that are happening).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, type fakeScheduler } from "../../../test-support/park/appHarness";
import { cleanup, q, qa } from "../../../test-support/park/componentsHarness";
import { liveApi, mountApp, seen, settle } from "../../../test-support/park/shellHarness";
import type { Api } from "../api/index";
import type { World, WorldState } from "../api/types";

const BAR = ".park-shell__runbar";
const RING = ".park-shell__ring";

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
  window.history.pushState({}, "", "/");
  Reflect.deleteProperty(window, "matchMedia");
});

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

const w = (id: string, st: WorldState, over: Partial<World> = {}): World => ({
  id,
  name: `World ${id}`,
  short: `World ${id}`,
  tier: "Village",
  tool: "Quick task",
  st,
  agents: 0,
  spend: "",
  spendV: 0,
  nextL: "",
  nextV: "",
  owner: "",
  started: "",
  ...over,
});

/** A live Api whose world list is whatever `served.worlds` holds right now. */
function servedApi(served: { worlds: World[] | "fail" }): Api {
  const api = liveApi(fakeApi());
  api.getWorlds = () =>
    served.worlds === "fail"
      ? Promise.reject(new Error("offline"))
      : Promise.resolve({ data: served.worlds, source: "live" as const });
  return api;
}

const bar = (): HTMLElement | null => document.querySelector<HTMLElement>(BAR);

/** The poll timer the bar arms while it shows (the injected scheduler; nothing else is running). */
async function poll(sch: ReturnType<typeof fakeScheduler>) {
  const t = sch.live().find((x) => x.ms >= 5000);
  expect(t, "the bar armed no re-read while it shows").toBeDefined();
  await act(async () => {
    sch.fire(t);
  });
  await settle();
}

function reduceMotion(on: boolean): void {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: on && /prefers-reduced-motion:\s*reduce/.test(query),
      media: query,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }),
  });
}

describe("RUN_INDICATOR bar: shown only while a recorded run is in progress", () => {
  it("RUN_INDICATOR_no_running_world_means_no_bar_on_any_page", async () => {
    const served = { worlds: [w("a", "finished"), w("b", "scheduled")] as World[] | "fail" };
    for (const path of ["/park/home", "/park/worlds", "/park/ledger", "/park/profile"]) {
      const { m } = await mountApp({ api: servedApi(served), path });
      expect(bar(), path).toBeNull();
      m.unmount();
    }
  });

  it("RUN_INDICATOR_the_fixture_Api_with_nothing_started_shows_no_bar_even_though_sample_worlds_say_running", async () => {
    await mountApp({ api: fakeApi() });
    expect(seen.store.getState().sources.fixture).toBe(true);
    expect(bar()).toBeNull();
  });

  it("RUN_INDICATOR_a_world_the_person_starts_on_the_fixture_path_shows_the_bar", async () => {
    await mountApp({ api: fakeApi() });
    act(() => {
      seen.app.addWorld("quick", "Find three venues");
    });
    await settle();
    const el = bar();
    expect(el).not.toBeNull();
    expect(el?.getAttribute("data-state")).toBe("running");
    expect(el?.getAttribute("data-source")).toBe("fixture");
    expect(seen.store.getState().sources.fixture).toBe(true); // the nav's Sample data chip logic still applies
  });

  it("RUN_INDICATOR_a_running_world_shows_the_bar_with_the_label_from_the_served_state", async () => {
    await mountApp({ api: servedApi({ worlds: [w("a", "running", { agents: 3 })] }) });
    const el = bar() as HTMLElement;
    expect(el).not.toBeNull();
    // <output> is the native status region (implicit role "status"); it is not an explicit role="status", which
    // the toast and the world card use and the older tests count.
    expect(el.tagName).toBe("OUTPUT");
    expect(el.getAttribute("aria-live")).toBe("polite");
    expect(el.getAttribute("data-state")).toBe("running");
    expect(el.textContent).toContain("3 agents working");
    expect(el.textContent).toContain("World a");
  });

  it("RUN_INDICATOR_the_label_follows_the_latest_read_and_a_terminal_state_removes_the_bar", async () => {
    const served = { worlds: [w("a", "running", { agents: 1 })] as World[] | "fail" };
    const { sch } = await mountApp({ api: servedApi(served) });
    expect(bar()?.textContent).toContain("1 agent working");

    served.worlds = [w("a", "running", { agents: 4 })];
    await poll(sch);
    expect(bar()?.textContent).toContain("4 agents working");
    expect(bar()?.textContent).not.toContain("1 agent working");

    served.worlds = [w("a", "finished", { agents: 4 })]; // world.completed
    await poll(sch);
    expect(bar()).toBeNull();
  });

  it("RUN_INDICATOR_a_failed_run_removes_the_bar_too_and_a_failed_read_shows_nothing", async () => {
    const served = { worlds: [w("a", "running")] as World[] | "fail" };
    const { sch } = await mountApp({ api: servedApi(served) });
    expect(bar()).not.toBeNull();
    served.worlds = "fail";
    await poll(sch);
    expect(bar(), "an unreadable state is not shown as running").toBeNull();
  });

  it("RUN_INDICATOR_after_the_terminal_event_nothing_is_re_read_on_a_timer", async () => {
    const served = { worlds: [w("a", "running")] as World[] | "fail" };
    const { sch } = await mountApp({ api: servedApi(served) });
    served.worlds = [w("a", "finished")];
    await poll(sch);
    expect(bar()).toBeNull();
    expect(sch.live().filter((t) => t.ms >= 5000)).toEqual([]);
  });
});

describe("RUN_INDICATOR bar: moving versus static", () => {
  it("RUN_INDICATOR_a_running_bar_has_the_spinning_ring_and_the_still_look_is_a_dot_that_never_moves", async () => {
    await mountApp({ api: servedApi({ worlds: [w("a", "running")] }) });
    expect(qa(bar() as HTMLElement, RING)).toHaveLength(1);
    expect(bar()?.getAttribute("data-motion")).toBe("on");
  });

  it("RUN_INDICATOR_a_held_run_shows_the_static_label_and_nothing_moves", async () => {
    await mountApp({ api: servedApi({ worlds: [w("a", "needs")] }) });
    const el = bar() as HTMLElement;
    expect(el.getAttribute("data-state")).toBe("held");
    expect(el.textContent).toContain("Waiting for your approval");
    expect(qa(el, RING)).toHaveLength(0);
    expect(el.querySelector("[data-spin]")).toBeNull();
  });

  it("RUN_INDICATOR_prefers_reduced_motion_removes_the_moving_ring_and_keeps_the_label", async () => {
    reduceMotion(true);
    await mountApp({ api: servedApi({ worlds: [w("a", "running", { agents: 2 })] }) });
    const el = bar() as HTMLElement;
    expect(el.getAttribute("data-motion")).toBe("off");
    expect(qa(el, RING)).toHaveLength(0);
    expect(el.textContent).toContain("2 agents working");
  });

  it("RUN_INDICATOR_the_still_motion_preference_removes_the_moving_ring_and_keeps_the_label", async () => {
    await mountApp({ api: servedApi({ worlds: [w("a", "running", { agents: 2 })] }) });
    expect(qa(bar() as HTMLElement, RING)).toHaveLength(1);
    act(() => seen.app.setPref("motion", "still"));
    await settle();
    const el = bar() as HTMLElement;
    expect(el.getAttribute("data-motion")).toBe("off");
    expect(qa(el, RING)).toHaveLength(0);
    expect(el.textContent).toContain("2 agents working");
  });
});

describe("RUN_INDICATOR bar: honest text, accessible, no noise", () => {
  it("RUN_INDICATOR_no_percentage_no_progressbar_no_meter_in_the_bar", async () => {
    await mountApp({
      api: servedApi({ worlds: [w("a", "running", { agents: 3, prog: 46 })] }),
    });
    const el = bar() as HTMLElement;
    expect(el.textContent).not.toMatch(/%|percent|46/);
    expect(el.querySelector('[role="progressbar"], progress, meter, [aria-valuenow]')).toBeNull();
  });

  it("RUN_INDICATOR_a_re_read_with_the_same_state_changes_nothing_in_the_live_region", async () => {
    const served = { worlds: [w("a", "running", { agents: 2 })] as World[] | "fail" };
    const { sch } = await mountApp({ api: servedApi(served) });
    const el = bar() as HTMLElement;
    const records: MutationRecord[] = [];
    const watch = new MutationObserver((r) => records.push(...r));
    watch.observe(el, { subtree: true, childList: true, characterData: true, attributes: true });
    served.worlds = [w("a", "running", { agents: 2 })]; // a new array, the same facts
    await poll(sch);
    await poll(sch);
    watch.disconnect();
    expect(bar()).toBe(el);
    expect(records.length, "the announced text is rewritten only when it changes").toBe(0);
  });

  it("RUN_INDICATOR_the_bar_is_not_a_button_and_holds_nothing_to_click", async () => {
    await mountApp({ api: servedApi({ worlds: [w("a", "running")] }) });
    const el = bar() as HTMLElement;
    expect(qa(el, "button, a, [tabindex], input")).toEqual([]);
  });

  it("RUN_INDICATOR_it_is_the_only_live_region_the_bar_adds_and_the_toast_still_finds_its_own", async () => {
    await mountApp({ api: servedApi({ worlds: [w("a", "running")] }) });
    expect(qa(document.body, '[role="status"]')).toHaveLength(0); // the bar adds no explicit role="status"
    act(() => seen.app.toast("Saved"));
    expect(qa(document.body, '[role="status"]')).toHaveLength(1);
  });

  it("RUN_INDICATOR_the_bar_sits_outside_main_so_a_page_swap_never_remounts_it", async () => {
    await mountApp({ api: servedApi({ worlds: [w("a", "running")] }) });
    expect(q(document.body, "main").contains(bar())).toBe(false);
    expect(qa(document.body, BAR)).toHaveLength(1);
  });
});
