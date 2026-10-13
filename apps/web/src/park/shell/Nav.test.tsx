// @vitest-environment happy-dom
// WEB-3b: the top nav (README "Shell > Nav"; reference `Tilo App.dc.html` header and its measured behaviour).
// Mounted through <AppShell/>, the one pinned entry point, and queried by role, label and text, the way a
// person (or a screen reader) finds things; numbers (sizes, radii, colours) are checked in the browser spec
// e2e/park-shell-visual.spec.ts against the values measured on the reference.
// Hooks the builder must expose, because the reference gives these elements no name or text:
//   the unread dot is the one non-svg child of the bell button.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  click,
  focus,
  pressDocument,
  q,
  qa,
} from "../../../test-support/park/componentsHarness";
import { liveApi, mountApp, seen } from "../../../test-support/park/shellHarness";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const TABS = [
  ["Home", "/"],
  ["Worlds", "/worlds"],
  ["Skills", "/skills"],
  ["Ledger", "/ledger"],
  ["Agenda", "/agenda"],
  ["Team", "/team"],
] as const;

const header = (root: ParentNode) => q(root, "header");
const tabs = (root: ParentNode) => qa<HTMLAnchorElement>(q(root, "header nav"), "a");
const label = (a: Element) => (a.textContent ?? "").replace(/\d+$/, "");
const currentLabels = (root: ParentNode) =>
  tabs(root)
    .filter((a) => a.getAttribute("aria-current") === "page")
    .map(label);
const byLabel = (root: ParentNode, name: string) =>
  q<HTMLButtonElement>(root, `button[aria-label="${name}"]`);
const bell = (root: ParentNode) => byLabel(root, "Notifications");
const avatar = (root: ParentNode) => byLabel(root, "Account menu");
const toggle = (root: ParentNode) => q<HTMLButtonElement>(root, 'button[aria-label^="Switch to"]');
const unreadDots = (root: ParentNode) =>
  [...bell(root).children].filter((c) => c.tagName.toLowerCase() !== "svg");
const sampleChip = (root: ParentNode) =>
  qa<HTMLButtonElement>(header(root), "button").find((b) => b.textContent === "Sample data");

describe("WEB_3b_nav: structure", () => {
  it("WEB_3b_nav_one_banner_with_one_labelled_Main_navigation", async () => {
    const { m } = await mountApp();
    expect(qa(m.container, "header")).toHaveLength(1);
    const navs = qa(header(m.container), "nav");
    expect(navs).toHaveLength(1);
    expect(navs[0]?.getAttribute("aria-label")).toBe("Main");
  });

  it("WEB_3b_nav_the_logo_is_a_home_link_that_reads_tilo_and_does_not_reload", async () => {
    const { m, navigate } = await mountApp({ path: "/park/ledger" });
    const logo = q<HTMLAnchorElement>(m.container, 'a[aria-label="Tilo home"]');
    expect(logo.getAttribute("href")).toBe("/");
    expect(logo.textContent).toBe("tilo");
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    act(() => {
      logo.dispatchEvent(ev);
    });
    expect(ev.defaultPrevented).toBe(true);
    expect(navigate).toHaveBeenCalledWith("/");
  });

  it("WEB_3b_nav_the_six_tabs_in_the_reference_order_link_to_their_park_paths", async () => {
    const { m } = await mountApp();
    expect(tabs(m.container).map((a) => [label(a), a.getAttribute("href")])).toEqual(
      TABS.map(([l, h]) => [l, h]),
    );
  });

  it("WEB_3b_nav_the_right_side_has_the_day_night_toggle_the_bell_and_the_AM_avatar_in_that_order", async () => {
    const { m } = await mountApp();
    const order = qa<HTMLButtonElement>(header(m.container), "button").map((b) =>
      b.getAttribute("aria-label"),
    );
    const named = order.filter((n) => n !== null);
    expect(named[0]).toBe("Your context");
    expect(named.slice(1)).toEqual(["Switch to night", "Notifications", "Account menu"]);
    expect(avatar(m.container).textContent).toBe("AM");
  });

  it("WEB_3b_nav_every_control_is_a_real_link_or_button_and_reachable_by_Tab", async () => {
    const { m } = await mountApp();
    for (const b of qa(header(m.container), "button")) {
      expect(b.getAttribute("type")).toBe("button");
      expect(b.getAttribute("tabindex")).not.toBe("-1");
    }
    for (const a of qa(header(m.container), "a")) {
      expect(a.getAttribute("href")).toMatch(/^\/(?!park(\/|$))/); // a root path, never the /park alias
      expect(a.getAttribute("tabindex")).not.toBe("-1");
    }
  });
});

describe("WEB_3b_nav: the active tab", () => {
  it("WEB_3b_nav_home_is_the_one_current_tab", async () => {
    const { m } = await mountApp();
    expect(currentLabels(m.container)).toEqual(["Home"]);
    for (const a of tabs(m.container).filter((x) => label(x) !== "Home")) {
      expect(a.hasAttribute("aria-current")).toBe(false);
    }
  });

  it("WEB_3b_nav_each_page_marks_its_own_tab_current", async () => {
    for (const [name, path] of TABS) {
      const { m } = await mountApp({ path });
      expect(currentLabels(m.container), path).toEqual([name]);
      m.unmount();
    }
  });

  it("WEB_3b_nav_a_world_page_keeps_the_Worlds_tab_current", async () => {
    const { m } = await mountApp({ path: "/park/world/k1" });
    expect(currentLabels(m.container)).toEqual(["Worlds"]);
  });

  it("WEB_3b_nav_profile_and_connectors_have_no_current_tab", async () => {
    for (const path of ["/park/profile", "/park/profile?tab=notifications", "/park/connectors"]) {
      const { m } = await mountApp({ path });
      expect(currentLabels(m.container), path).toEqual([]);
      m.unmount();
    }
  });
});

describe("WEB_3b_nav: tabs navigate through app.go", () => {
  it("WEB_3b_nav_a_tab_click_is_kept_from_loading_the_page_and_goes_to_its_path", async () => {
    for (const [name, path] of TABS) {
      const { m, navigate } = await mountApp();
      const a = tabs(m.container).find((x) => label(x) === name) as HTMLAnchorElement;
      const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
      act(() => {
        a.dispatchEvent(ev);
      });
      expect(ev.defaultPrevented, name).toBe(true);
      expect(navigate, name).toHaveBeenCalledTimes(1);
      expect(navigate, name).toHaveBeenCalledWith(path);
      m.unmount();
    }
  });

  it("WEB_3b_nav_a_modified_click_is_left_to_the_browser", async () => {
    const { m, navigate } = await mountApp();
    const a = tabs(m.container)[3] as HTMLAnchorElement;
    for (const init of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { button: 1 }]) {
      const ev = new MouseEvent("click", { bubbles: true, cancelable: true, ...init });
      act(() => {
        a.dispatchEvent(ev);
      });
      expect(ev.defaultPrevented, JSON.stringify(init)).toBe(false);
    }
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe("WEB_3b_nav: the Worlds badge shows what still needs you", () => {
  const worlds = (root: ParentNode) => tabs(root).find((a) => label(a) === "Worlds") as HTMLElement;

  it("WEB_3b_nav_two_decisions_wait_so_the_badge_reads_2_on_Worlds_only", async () => {
    const { m } = await mountApp();
    expect(worlds(m.container).textContent).toBe("Worlds2");
    expect(tabs(m.container).filter((a) => /\d/.test(a.textContent ?? ""))).toHaveLength(1);
  });

  it("WEB_3b_nav_each_approval_lowers_it_and_at_zero_it_is_gone_not_0", async () => {
    const { m } = await mountApp();
    act(() => seen.app.decide("depot"));
    expect(worlds(m.container).textContent).toBe("Worlds1");
    act(() => seen.app.decide("mail"));
    expect(worlds(m.container).textContent).toBe("Worlds");
    act(() => seen.store.getState().toast?.action?.()); // Undo the supplier brief
    expect(worlds(m.container).textContent).toBe("Worlds1");
  });
});

describe("WEB_3b_nav: day and night", () => {
  it("WEB_3b_nav_the_toggle_names_the_theme_it_switches_to", async () => {
    const { m } = await mountApp();
    expect(toggle(m.container).getAttribute("aria-label")).toBe("Switch to night");
    expect(toggle(m.container).getAttribute("title")).toBe("Switch to night");
    click(toggle(m.container));
    expect(toggle(m.container).getAttribute("aria-label")).toBe("Switch to day");
    expect(toggle(m.container).getAttribute("title")).toBe("Switch to day");
  });

  it("WEB_3b_nav_the_toggle_sets_the_time_pref_both_ways", async () => {
    const { m, api } = await mountApp();
    click(toggle(m.container));
    expect(seen.app.time).toBe("night");
    expect(api.setPref).toHaveBeenCalledWith("time", "night");
    click(toggle(m.container));
    expect(seen.app.time).toBe("day");
    expect(api.setPref).toHaveBeenLastCalledWith("time", "day");
  });

  it("WEB_3b_nav_the_toggle_icon_changes_with_the_theme", async () => {
    const { m } = await mountApp();
    const day = q(toggle(m.container), "svg").outerHTML;
    click(toggle(m.container));
    expect(q(toggle(m.container), "svg").outerHTML).not.toBe(day);
  });
});

describe("WEB_3b_nav: bell and avatar", () => {
  it("WEB_3b_nav_the_bell_opens_and_closes_the_notifications_and_says_so_in_aria_expanded", async () => {
    const { m } = await mountApp();
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("false");
    click(bell(m.container));
    expect(seen.store.getState().menu).toBe("notif");
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("true");
    click(bell(m.container));
    expect(seen.store.getState().menu).toBeNull();
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("false");
  });

  it("WEB_3b_nav_the_amber_dot_shows_until_the_bell_is_opened_and_stays_gone", async () => {
    const { m } = await mountApp();
    expect(unreadDots(m.container)).toHaveLength(1);
    click(bell(m.container));
    expect(unreadDots(m.container)).toHaveLength(0);
    click(bell(m.container));
    expect(unreadDots(m.container)).toHaveLength(0);
  });

  it("WEB_3b_nav_nothing_waiting_means_no_dot_even_if_never_opened", async () => {
    const { m } = await mountApp();
    act(() => seen.app.decide("depot"));
    expect(unreadDots(m.container)).toHaveLength(1);
    act(() => seen.app.decide("mail"));
    expect(seen.store.getState().read).toBe(false);
    expect(unreadDots(m.container)).toHaveLength(0);
  });

  it("WEB_3b_nav_the_avatar_opens_the_account_menu_and_says_so_in_aria_expanded", async () => {
    const { m } = await mountApp();
    expect(avatar(m.container).getAttribute("aria-expanded")).toBe("false");
    click(avatar(m.container));
    expect(seen.store.getState().menu).toBe("acct");
    expect(avatar(m.container).getAttribute("aria-expanded")).toBe("true");
  });

  it("WEB_3b_nav_only_one_of_the_two_menus_is_open_at_a_time", async () => {
    const { m } = await mountApp();
    click(bell(m.container));
    click(avatar(m.container));
    expect(seen.store.getState().menu).toBe("acct");
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("false");
    click(bell(m.container));
    expect(seen.store.getState().menu).toBe("notif");
    expect(avatar(m.container).getAttribute("aria-expanded")).toBe("false");
  });
});

describe("WEB_3b_chip: Sample data (plan section 6.1)", () => {
  const SAMPLE = "Northwind Ops is a fictional team. Amounts are examples (£), dates follow today.";

  it("WEB_3b_chip_a_fixture_Api_shows_the_chip_in_the_nav_with_no_page_asking_for_data", async () => {
    const { m } = await mountApp();
    expect(seen.store.getState().sources.fixture).toBe(true);
    expect(sampleChip(m.container)).toBeDefined();
  });

  it("WEB_3b_chip_it_uses_the_StatusChip_component", async () => {
    const { m } = await mountApp();
    expect(sampleChip(m.container)?.querySelector(".park-chip")).not.toBeNull();
  });

  it("WEB_3b_chip_a_live_only_Api_shows_no_chip", async () => {
    const { m } = await mountApp({ api: liveApi() });
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: true });
    expect(sampleChip(m.container)).toBeUndefined();
  });

  it("WEB_3b_chip_a_live_result_after_a_fixture_one_does_not_hide_it", async () => {
    const { m } = await mountApp();
    act(() => seen.store.noteSource("live"));
    expect(sampleChip(m.container)).toBeDefined();
  });

  it("WEB_3b_chip_clicking_opens_the_explanation_and_Escape_closes_it_with_focus_back", async () => {
    const { m } = await mountApp();
    const chip = sampleChip(m.container) as HTMLButtonElement;
    focus(chip);
    click(chip);
    const text = q(document.body, '[role="dialog"]').textContent;
    expect(text).toContain(SAMPLE);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    pressDocument("Escape");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(chip);
  });

  it("WEB_3b_chip_it_is_not_one_of_the_two_menus_of_the_store", async () => {
    const { m } = await mountApp();
    click(sampleChip(m.container) as HTMLButtonElement);
    expect(seen.store.getState().menu).toBeNull();
  });
});
