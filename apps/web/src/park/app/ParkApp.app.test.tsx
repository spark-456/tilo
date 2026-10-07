// @vitest-environment happy-dom
// WEB-3a: what the shell hands every page (the `app` prop) and the toast it draws from the store.
// The registry is replaced by one probe page per id, so the test sees exactly what a real page would.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../test-support/park/componentsHarness";
import type { AppCtx } from "./AppCtx";
import { ParkApp } from "./ParkApp";

const held = vi.hoisted(() => ({
  app: undefined as AppCtx | undefined,
  pagesSeen: [] as string[],
}));

vi.mock("./pages", async () => {
  const { lazy, createElement } = await import("react");
  const make = (id: string) =>
    lazy(() =>
      Promise.resolve({
        default: ({ app }: { app: AppCtx }) => {
          held.app = app;
          held.pagesSeen.push(id);
          return createElement(
            "div",
            { "data-testid": `probe-${id}` },
            createElement("h1", { tabIndex: -1 }, `Probe ${id}`),
          );
        },
      }),
    );
  const ids = [
    "home",
    "worlds",
    "world",
    "skills",
    "ledger",
    "agenda",
    "team",
    "profile",
    "connectors",
  ];
  return { PAGES: Object.fromEntries(ids.map((id) => [id, make(id)])) };
});

const app = (): AppCtx => {
  if (!held.app) throw new Error("no page rendered yet");
  return held.app;
};
const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};
const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<ParkApp />);
  await settle();
  return m;
};
const toastEl = (root: ParentNode) => root.querySelector<HTMLElement>('[role="status"]');

afterEach(() => {
  vi.useRealTimers();
  cleanup();
  window.history.pushState({}, "", "/");
  held.app = undefined;
  held.pagesSeen.length = 0;
});

describe("WEB_3a_shell: the page gets the app prop", () => {
  it("WEB_3a_shell_the_registry_page_for_the_route_is_the_one_rendered", async () => {
    const m = await visit("/park/ledger");
    expect(m.container.querySelector('[data-testid="probe-ledger"]')).not.toBeNull();
    expect([...new Set(held.pagesSeen)]).toEqual(["ledger"]);
  });

  it("WEB_3a_shell_app_carries_page_params_and_the_pinned_defaults", async () => {
    await visit("/park/skills?id=sk3&x=1");
    expect(app()).toMatchObject({
      page: "skills",
      params: { id: "sk3" },
      dec: {},
      needsLeft: 2,
      added: [],
      time: "day",
      night: false,
      motion: "calm",
      pins: expect.any(Array), // WEB-3b: the pins come from the city backdrop
      ready: true,
    });
    expect(app().vw).toBeGreaterThan(0);
    expect(app().vh).toBeGreaterThan(0);
  });

  it("WEB_3a_shell_world_page_gets_the_id", async () => {
    await visit("/park/world/k1");
    expect(app().page).toBe("world");
    expect(app().params).toEqual({ id: "k1" });
  });

  it("WEB_3a_shell_go_changes_the_url_and_the_page", async () => {
    const m = await visit("/park/home");
    // WEB-3b: a world always opens through the loader; the page swaps at its third 340 ms step.
    vi.useFakeTimers();
    await act(async () => app().go("world", { id: "k1" }));
    expect(window.location.pathname).toBe("/park/home");
    await act(async () => {
      vi.advanceTimersByTime(340 * 3);
    });
    await settle();
    expect(window.location.pathname).toBe("/world/k1");
    expect(m.container.querySelector('[data-testid="probe-world"]')).not.toBeNull();
    expect(document.title).toBe("World · Tilo");
    await act(async () => app().go("skills", { id: "sk2" }));
    await settle();
    expect(window.location.pathname + window.location.search).toBe("/skills?id=sk2");
    expect(app().params).toEqual({ id: "sk2" });
  });

  it("WEB_3a_shell_focus_goes_to_the_h1_of_the_page_go_opened", async () => {
    const m = await visit("/park/home");
    await act(async () => app().go("agenda"));
    await settle();
    expect(document.activeElement).toBe(q(m.container, "h1"));
  });

  it("WEB_3a_shell_setPref_night_sets_data_time_on_the_root", async () => {
    const m = await visit("/park/home");
    await act(async () => app().setPref("time", "night"));
    expect(q(m.container, "[data-park]").getAttribute("data-time")).toBe("night");
    expect(app().night).toBe(true);
    await act(async () => app().setPref("time", "day"));
    expect(q(m.container, "[data-park]").getAttribute("data-time")).toBe("day");
  });
});

describe("WEB_3a_shell: the toast", () => {
  it("WEB_3a_shell_no_toast_until_something_toasts", async () => {
    const m = await visit("/park/home");
    expect(toastEl(m.container)).toBeNull();
  });

  it("WEB_3a_shell_decide_shows_the_toast_with_Undo_inside_the_park_root", async () => {
    const m = await visit("/park/home");
    await act(async () => app().decide("depot"));
    const t = toastEl(m.container);
    expect(t?.textContent).toContain("Approved £3,420 for Laptop Depot");
    expect(t?.closest("[data-park]")).not.toBeNull(); // the tokens apply to it
    expect(t?.getAttribute("aria-live")).toBe("polite");
    const undo = qa<HTMLButtonElement>(t as HTMLElement, "button");
    expect(undo.map((b) => b.textContent)).toEqual(["Undo"]);
    expect(qa(m.container, '[role="status"]')).toHaveLength(1);
  });

  it("WEB_3a_shell_Undo_restores_the_decision_and_removes_the_toast", async () => {
    const m = await visit("/park/home");
    await act(async () => app().decide("mail"));
    expect(toastEl(m.container)?.textContent).toContain("Supplier brief sent to 3 suppliers");
    click(q(toastEl(m.container) as HTMLElement, "button"));
    expect(app().dec.mail).toBe(false);
    expect(app().needsLeft).toBe(2);
    expect(toastEl(m.container)).toBeNull();
  });

  it("WEB_3a_shell_a_second_toast_replaces_the_first", async () => {
    const m = await visit("/park/home");
    await act(async () => app().toast("First"));
    await act(async () => app().toast("Second"));
    expect(qa(m.container, '[role="status"]')).toHaveLength(1);
    expect(toastEl(m.container)?.textContent).toContain("Second");
  });

  it("WEB_3a_shell_the_toast_hides_after_4200_ms_on_the_real_scheduler", async () => {
    const m = await visit("/park/home");
    vi.useFakeTimers();
    await act(async () => app().toast("Saved"));
    expect(toastEl(m.container)).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(4199);
    });
    expect(toastEl(m.container)).not.toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(toastEl(m.container)).toBeNull();
  });

  it("WEB_3a_shell_addWorld_toast_Open_goes_to_the_new_world", async () => {
    const m = await visit("/park/home");
    await act(async () => {
      app().addWorld("quick", "Order lunch");
    });
    expect(toastEl(m.container)?.textContent).toContain("Started “Order lunch”");
    const open = qa<HTMLButtonElement>(m.container, '[role="status"] button');
    expect(open.map((b) => b.textContent)).toEqual(["Open"]);
    click(open[0] as HTMLButtonElement);
    await settle();
    expect(window.location.pathname).toBe("/world/new1");
    expect(app().params).toEqual({ id: "new1" });
    expect(toastEl(m.container)).toBeNull();
  });

  it("WEB_3a_shell_the_toast_stays_across_a_route_change", async () => {
    const m = await visit("/park/home");
    await act(async () => app().decide("depot"));
    await act(async () => app().go("worlds"));
    await settle();
    expect(toastEl(m.container)?.textContent).toContain("Approved £3,420 for Laptop Depot");
  });
});
