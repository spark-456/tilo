// @vitest-environment happy-dom
// WEB-6 acceptance: the World page inside the real shell (<ParkApp/>, the real store and registry, the
// fixture Api). Pinned: plan section 10 ("one line for your page in park/app/pages.ts", the id added to
// REAL_PAGES so the WEB-3a placeholder checks skip it while the generic checks keep covering the route),
// WEB-3a (one <main>, `data-testid="park-page-world"`, "<Page> · Tilo" title, focus to the new h1 after a
// route change) and README "Approve: decide(key) -> toast with Undo" (the toast is the store's).
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { PLACEHOLDER_PAGES, REAL_PAGES } from "../../../../test-support/park/realPages";
import {
  breadcrumb,
  control,
  elWithText,
  hasControl,
  pageText,
  textOf,
} from "../../../../test-support/park/worldHarness";
import { ParkApp } from "../../app/ParkApp";

const settle = async () => {
  for (let i = 0; i < 4; i++) {
    await act(async () => {
      await vi.dynamicImportSettled();
      await new Promise<void>((r) => setTimeout(r, 0));
    });
  }
};
const visit = async (path: string) => {
  window.history.pushState({}, "", path);
  const m = mount(<ParkApp />);
  await settle();
  return m;
};
const goTo = async (path: string) => {
  await act(async () => {
    window.history.pushState({}, "", path);
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await settle();
};

/** The live toast (role status) that says `part`. */
const toastWith = (part: string): HTMLElement => {
  const hit = qa(document.body, '[role="status"]').find((e) => textOf(e).includes(part));
  if (!hit) throw new Error(`no toast says "${part}"`);
  return hit;
};

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  document.title = "";
});

describe("WEB_6_shell: the registry", () => {
  it("WEB_6_shell_pages_ts_holds_one_world_line_that_imports_the_page_and_the_others_stay", () => {
    const src = readFileSync(join(__dirname, "..", "..", "app", "pages.ts"), "utf8");
    const lines = src.split(/\r?\n/).filter((l) => /^\s*world\s*:/.test(l));
    expect(lines).toHaveLength(1);
    expect(lines[0]).toMatch(/pages\/World\/WorldPage/);
    expect(lines[0]).toMatch(/\.then\(\(m\) => \(\{ default: m\.WorldPage \}\)\)/);
    expect(lines[0]).not.toMatch(/Placeholder/);
    // `worlds` and `profile` are other lanes' pages: this ticket does not touch them
    for (const id of [
      "home",
      "worlds",
      "skills",
      "ledger",
      "agenda",
      "team",
      "profile",
      "connectors",
    ]) {
      expect(
        src.split(/\r?\n/).filter((l) => new RegExp(`^\\s*${id}\\s*:`).test(l)),
        id,
      ).toHaveLength(1);
    }
  });

  it("WEB_6_shell_REAL_PAGES_lists_world_so_the_placeholder_checks_skip_it", () => {
    expect(REAL_PAGES).toContain("world");
    expect(PLACEHOLDER_PAGES).not.toContain("world");
  });
});

describe("WEB_6_shell: /park/world/<id> inside the shell", () => {
  it("WEB_6_shell_the_route_renders_the_page_in_the_single_main_with_one_h1_and_the_title", async () => {
    const m = await visit("/park/world/k1");
    const mains = qa(m.container, "main");
    expect(mains).toHaveLength(1);
    expect(mains[0]?.querySelector('[data-testid="park-page-world"]')).not.toBeNull();
    expect(qa(m.container, '[data-testid^="park-page-"]')).toHaveLength(1);
    expect(qa(m.container, "h1")).toHaveLength(1);
    expect(textOf(q(m.container, "h1"))).toBe("K1 electric scooter");
    expect(document.title).toBe("World · Tilo");
    expect(mains[0]?.closest("[data-park]")).not.toBeNull();
    expect(pageText(m.container)).not.toContain("Not built yet");
  });

  it("WEB_6_shell_the_sheet_sits_in_the_page_column_and_the_nav_is_outside_the_main", async () => {
    const m = await visit("/park/world/k1");
    const main = q(m.container, "main");
    expect(main.querySelectorAll("section.park-sheet")).toHaveLength(1);
    expect(main.querySelector("nav[aria-label='Breadcrumb']")).not.toBeNull();
    expect(qa(m.container, "header").length).toBeGreaterThanOrEqual(1); // the top nav
  });

  it("WEB_6_shell_another_id_swaps_the_world_and_focus_goes_to_the_new_h1", async () => {
    const m = await visit("/park/world/k1");
    await goTo("/park/world/hires");
    const h1 = q(m.container, "h1");
    expect(textOf(h1)).toBe("Onboard 12 new hires");
    expect(qa(m.container, "h1")).toHaveLength(1);
    expect(document.activeElement).toBe(h1);
  });

  it("WEB_6_shell_an_unknown_id_still_opens_the_page_with_the_fallback_world", async () => {
    const m = await visit("/park/home");
    expect(m.container.querySelector('[data-testid="park-page-world"]')).toBeNull();
    await goTo("/park/world/nope");
    expect(m.container.querySelector('[data-testid="park-page-world"]')).not.toBeNull();
  });

  it("WEB_6_shell_the_breadcrumb_goes_back_to_worlds_and_the_Spend_link_to_the_ledger", async () => {
    const m = await visit("/park/world/k1");
    click(control(breadcrumb(m.container), "Worlds"));
    await settle();
    expect(window.location.pathname).toBe("/worlds");
    expect(m.container.querySelector('[data-testid="park-page-worlds"]')).not.toBeNull();
    await goTo("/park/world/k1");
    const spend = elWithText(m.container, "Spend") as HTMLElement;
    let card: HTMLElement | null = spend;
    while (card && !hasControl(card, "Ledger")) card = card.parentElement;
    click(control(card as HTMLElement, "Ledger"));
    await settle();
    expect(window.location.pathname).toBe("/ledger");
  });

  it("WEB_6_shell_Approve_goes_through_the_store_toast_with_Undo_and_the_card_updates", async () => {
    const m = await visit("/park/world/k1");
    click(control(m.container, "Approve £3,420"));
    await settle();
    const toast = toastWith("Approved £3,420 for Laptop Depot");
    expect(hasControl(toast, "Undo")).toBe(true);
    expect(hasControl(m.container, "Approve £3,420")).toBe(false);
    expect(textOf(m.container)).toContain("Approved · just now");
    expect(elWithText(m.container, "1 decision before agents continue")).toBeTruthy();
    // Undo puts the decision back
    click(control(toast, "Undo"));
    await settle();
    expect(hasControl(m.container, "Approve £3,420")).toBe(true);
    expect(elWithText(m.container, "2 decisions before agents continue")).toBeTruthy();
  });

  it("WEB_6_shell_Pause_shows_the_store_toast_line", async () => {
    const m = await visit("/park/world/k1");
    click(control(m.container, "Pause"));
    await settle();
    expect(toastWith("Paused. No spend while paused")).toBeTruthy();
    expect(elWithText(m.container, "Paused · agents are waiting")).toBeTruthy();
  });

  it("WEB_6_shell_the_page_makes_no_console_error_or_warning", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    await visit("/park/world/k1");
    cleanup();
    await visit("/park/world/northline");
    cleanup();
    await visit("/park/world/calls");
    expect(error.mock.calls).toEqual([]);
    expect(warn.mock.calls).toEqual([]);
    vi.restoreAllMocks();
  });
});
