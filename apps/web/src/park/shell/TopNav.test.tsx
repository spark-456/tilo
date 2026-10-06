// @vitest-environment happy-dom
// WEB-3b: <TopNav/> (README "Shell > Nav"; reference `Tilo App.dc.html` header). Pinned surface,
// park/shell/TopNav.tsx: named export `TopNav()`, no props; it reads useApp() and the store.
// Markup: `header.park-nav` > a.park-nav__logo[aria-label="Tilo home"] (div.park-nav__tile > div.park-nav__visor >
// two span.park-nav__eye; div.park-nav__word "tilo"), `nav.park-nav__tabs[aria-label="Main"]` with six
// `a.park-nav__tab` (the Worlds one holds `span.park-nav__badge`), then the day/night `button.park-nav__icon`,
// the bell `button.park-nav__icon[aria-label="Notifications"]` (with `span.park-nav__unread`), the avatar
// `button.park-nav__avatar[aria-label="Account menu"]` ("AM", plus `park-nav__avatar--ring` while the account
// menu is open or the page is profile or connectors), the `button.park-nav__chip` "Sample data" (only when a
// fixture result was read), and `div.park-nav__bar[aria-hidden="true"]`, the static 3px progress element.
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, click, focus, pressDocument, q, qa } from "../../../test-support/park/componentsHarness";
import { liveApi, mountShell, seen } from "../../../test-support/park/shellHarness";
import { TopNav } from "./TopNav";

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const TABS = [
  ["Home", "/park/home"],
  ["Worlds", "/park/worlds"],
  ["Skills", "/park/skills"],
  ["Ledger", "/park/ledger"],
  ["Agenda", "/park/agenda"],
  ["Team", "/park/team"],
] as const;

const header = (root: ParentNode) => q(root, "header.park-nav");
const tabs = (root: ParentNode) => qa<HTMLAnchorElement>(root, "nav a.park-nav__tab");
const label = (a: Element) => (a.textContent ?? "").replace(/\d+$/, "");
const current = (root: ParentNode) =>
  tabs(root)
    .filter((a) => a.getAttribute("aria-current") === "page")
    .map(label);
const bell = (root: ParentNode) => q<HTMLButtonElement>(root, 'button[aria-label="Notifications"]');
const avatar = (root: ParentNode) => q<HTMLButtonElement>(root, 'button[aria-label="Account menu"]');
const toggle = (root: ParentNode) =>
  q<HTMLButtonElement>(root, 'button[aria-label^="Switch to"]');

describe("WEB_3b_nav: structure", () => {
  it("WEB_3b_nav_is_one_banner_with_one_Main_navigation", () => {
    const { m } = mountShell(<TopNav />);
    expect(qa(m.container, "header.park-nav")).toHaveLength(1);
    const navs = qa(header(m.container), "nav");
    expect(navs).toHaveLength(1);
    expect(navs[0]?.getAttribute("aria-label")).toBe("Main");
  });

  it("WEB_3b_nav_logo_is_a_home_link_with_the_tile_the_visor_two_dots_and_the_wordmark", () => {
    const { m, navigate } = mountShell(<TopNav />, { path: "/park/ledger" });
    const logo = q<HTMLAnchorElement>(m.container, 'a[aria-label="Tilo home"]');
    expect(logo.getAttribute("href")).toBe("/park/home");
    expect(qa(logo, ".park-nav__tile .park-nav__visor .park-nav__eye")).toHaveLength(2);
    expect(q(logo, ".park-nav__word").textContent).toBe("tilo");
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, button: 0 });
    act(() => {
      logo.dispatchEvent(ev);
    });
    expect(ev.defaultPrevented).toBe(true);
    expect(navigate).toHaveBeenCalledWith("/park/home");
  });

  it("WEB_3b_nav_has_the_six_tabs_in_the_reference_order_as_links_to_park_paths", () => {
    const { m } = mountShell(<TopNav />);
    expect(tabs(m.container).map((a) => [label(a), a.getAttribute("href")])).toEqual(
      TABS.map(([l, h]) => [l, h]),
    );
  });

  it("WEB_3b_nav_the_right_side_has_the_toggle_the_bell_and_the_AM_avatar_in_that_order", () => {
    const { m } = mountShell(<TopNav />);
    const order = qa<HTMLElement>(
      header(m.container),
      "button.park-nav__icon, button.park-nav__avatar",
    ).map((b) => b.getAttribute("aria-label"));
    expect(order).toHaveLength(3);
    expect(order[0]).toMatch(/^Switch to (day|night)$/);
    expect(order.slice(1)).toEqual(["Notifications", "Account menu"]);
    expect(avatar(m.container).textContent).toBe("AM");
  });

  it("WEB_3b_nav_every_control_is_a_real_button_or_link_and_none_is_skipped_by_Tab", () => {
    const { m } = mountShell(<TopNav />);
    for (const b of qa(header(m.container), "button")) {
      expect(b.getAttribute("type"), b.getAttribute("aria-label") ?? "").toBe("button");
      expect(b.getAttribute("tabindex")).not.toBe("-1");
    }
    for (const a of qa(header(m.container), "a")) {
      expect(a.getAttribute("href")).toMatch(/^\/park\//);
      expect(a.getAttribute("tabindex")).not.toBe("-1");
    }
  });

  it("WEB_3b_nav_has_the_static_3px_progress_element_hidden_from_assistive_tech", () => {
    const { m } = mountShell(<TopNav />);
    const bar = q(header(m.container), ".park-nav__bar");
    expect(bar.getAttribute("aria-hidden")).toBe("true");
    expect(bar.textContent).toBe("");
  });
});

describe("WEB_3b_nav: the active tab", () => {
  it("WEB_3b_nav_home_is_current_and_only_home", () => {
    const { m } = mountShell(<TopNav />);
    expect(current(m.container)).toEqual(["Home"]);
    for (const a of tabs(m.container).filter((x) => label(x) !== "Home")) {
      expect(a.hasAttribute("aria-current")).toBe(false);
    }
    expect(tabs(m.container).filter((a) => a.classList.contains("park-nav__tab--on"))).toHaveLength(1);
  });

  it("WEB_3b_nav_each_page_marks_its_own_tab_current", () => {
    for (const [name, path] of TABS) {
      const { m } = mountShell(<TopNav />, { path });
      expect(current(m.container), path).toEqual([name]);
      expect(
        tabs(m.container).find((a) => a.classList.contains("park-nav__tab--on"))?.getAttribute("href"),
      ).toBe(path);
      m.unmount();
    }
  });

  it("WEB_3b_nav_a_world_page_keeps_the_Worlds_tab_current", () => {
    const { m } = mountShell(<TopNav />, { path: "/park/world/k1" });
    expect(current(m.container)).toEqual(["Worlds"]);
  });

  it("WEB_3b_nav_profile_and_connectors_have_no_current_tab", () => {
    for (const path of ["/park/profile", "/park/profile?tab=notifications", "/park/connectors"]) {
      const { m } = mountShell(<TopNav />, { path });
      expect(current(m.container), path).toEqual([]);
      m.unmount();
    }
  });
});

describe("WEB_3b_nav: tabs navigate through app.go", () => {
  it("WEB_3b_nav_clicking_a_tab_prevents_the_page_load_and_goes_to_its_path", () => {
    for (const [name, path] of TABS) {
      const { m, navigate } = mountShell(<TopNav />);
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

  it("WEB_3b_nav_a_modified_click_is_left_to_the_browser", () => {
    const { m, navigate } = mountShell(<TopNav />);
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

  it("WEB_3b_nav_the_avatar_and_bell_do_not_navigate_they_open_menus", () => {
    const { m, navigate } = mountShell(<TopNav />);
    click(bell(m.container));
    click(avatar(m.container));
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe("WEB_3b_nav: the Worlds badge", () => {
  it("WEB_3b_nav_the_badge_shows_needsLeft_on_the_Worlds_tab_only", () => {
    const { m } = mountShell(<TopNav />);
    const badges = qa(m.container, ".park-nav__badge");
    expect(badges).toHaveLength(1);
    expect(badges[0]?.textContent).toBe("2");
    expect(badges[0]?.closest("a")?.getAttribute("href")).toBe("/park/worlds");
  });

  it("WEB_3b_nav_the_badge_follows_the_decisions_and_is_gone_at_zero", () => {
    const { m } = mountShell(<TopNav />);
    act(() => seen.app.decide("depot"));
    expect(q(m.container, ".park-nav__badge").textContent).toBe("1");
    act(() => seen.app.decide("mail"));
    expect(qa(m.container, ".park-nav__badge")).toHaveLength(0); // hidden, not "0"
    expect(tabs(m.container).map((a) => a.textContent)).toEqual(TABS.map(([l]) => l));
    act(() => seen.store.getState().toast?.action?.()); // Undo the mail brief
    expect(q(m.container, ".park-nav__badge").textContent).toBe("1");
  });
});

describe("WEB_3b_nav: day and night", () => {
  it("WEB_3b_nav_the_toggle_names_the_theme_it_switches_to", () => {
    const { m } = mountShell(<TopNav />);
    const b = toggle(m.container);
    expect(b.getAttribute("aria-label")).toBe("Switch to night");
    expect(b.getAttribute("title")).toBe("Switch to night");
    click(b);
    expect(toggle(m.container).getAttribute("aria-label")).toBe("Switch to day");
    expect(toggle(m.container).getAttribute("title")).toBe("Switch to day");
  });

  it("WEB_3b_nav_the_toggle_calls_setPref_time_both_ways", () => {
    const { m, api } = mountShell(<TopNav />);
    click(toggle(m.container));
    expect(seen.store.getState().time).toBe("night");
    expect(seen.app.night).toBe(true);
    expect(api.setPref).toHaveBeenCalledWith("time", "night");
    click(toggle(m.container));
    expect(seen.store.getState().time).toBe("day");
    expect(api.setPref).toHaveBeenLastCalledWith("time", "day");
  });

  it("WEB_3b_nav_the_icon_is_a_kit_svg_and_changes_with_the_theme", () => {
    const { m } = mountShell(<TopNav />);
    const day = q(toggle(m.container), "svg").outerHTML;
    click(toggle(m.container));
    const night = q(toggle(m.container), "svg").outerHTML;
    expect(day).not.toBe(night);
  });
});

describe("WEB_3b_nav: the bell", () => {
  it("WEB_3b_nav_the_bell_toggles_the_notifications_menu_and_aria_expanded", () => {
    const { m } = mountShell(<TopNav />);
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("false");
    click(bell(m.container));
    expect(seen.store.getState().menu).toBe("notif");
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("true");
    click(bell(m.container));
    expect(seen.store.getState().menu).toBeNull();
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("false");
  });

  it("WEB_3b_nav_the_amber_dot_shows_until_the_bell_is_opened_and_stays_gone", () => {
    const { m } = mountShell(<TopNav />);
    expect(qa(bell(m.container), ".park-nav__unread")).toHaveLength(1);
    click(bell(m.container));
    expect(qa(bell(m.container), ".park-nav__unread")).toHaveLength(0);
    click(bell(m.container));
    expect(qa(bell(m.container), ".park-nav__unread")).toHaveLength(0);
  });

  it("WEB_3b_nav_no_dot_when_nothing_needs_you_even_if_unread", () => {
    const { m } = mountShell(<TopNav />);
    act(() => seen.app.decide("depot"));
    expect(qa(bell(m.container), ".park-nav__unread")).toHaveLength(1);
    act(() => seen.app.decide("mail"));
    expect(seen.store.getState().read).toBe(false);
    expect(qa(bell(m.container), ".park-nav__unread")).toHaveLength(0);
  });
});

describe("WEB_3b_nav: the avatar", () => {
  it("WEB_3b_nav_the_avatar_opens_the_account_menu_and_aria_expanded_follows", () => {
    const { m } = mountShell(<TopNav />);
    expect(avatar(m.container).getAttribute("aria-expanded")).toBe("false");
    click(avatar(m.container));
    expect(seen.store.getState().menu).toBe("acct");
    expect(avatar(m.container).getAttribute("aria-expanded")).toBe("true");
  });

  it("WEB_3b_nav_only_one_menu_is_open_at_a_time", () => {
    const { m } = mountShell(<TopNav />);
    click(bell(m.container));
    click(avatar(m.container));
    expect(seen.store.getState().menu).toBe("acct");
    expect(bell(m.container).getAttribute("aria-expanded")).toBe("false");
    click(bell(m.container));
    expect(seen.store.getState().menu).toBe("notif");
    expect(avatar(m.container).getAttribute("aria-expanded")).toBe("false");
  });

  it("WEB_3b_nav_the_hero_ring_shows_on_profile_connectors_and_while_the_account_menu_is_open", () => {
    const ring = (root: ParentNode) => avatar(root).classList.contains("park-nav__avatar--ring");
    for (const [path, want] of [
      ["/park/home", false],
      ["/park/ledger", false],
      ["/park/profile", true],
      ["/park/connectors", true],
    ] as const) {
      const { m } = mountShell(<TopNav />, { path });
      expect(ring(m.container), path).toBe(want);
      m.unmount();
    }
    const { m } = mountShell(<TopNav />);
    click(avatar(m.container));
    expect(ring(m.container)).toBe(true);
    click(avatar(m.container));
    expect(ring(m.container)).toBe(false);
  });
});

describe("WEB_3b_nav: the Sample data chip (plan section 6.1)", () => {
  const SAMPLE =
    "Northwind Ops is a fictional team. Amounts are examples (£), dates are September 2026.";
  const chip = (root: ParentNode) => root.querySelector<HTMLButtonElement>("button.park-nav__chip");

  it("WEB_3b_nav_no_chip_before_anything_was_read", () => {
    const { m } = mountShell(<TopNav />);
    expect(chip(m.container)).toBeNull();
  });

  it("WEB_3b_nav_a_fixture_result_shows_the_chip_inside_the_nav", async () => {
    const { m } = mountShell(<TopNav />);
    await act(async () => {
      await seen.api.getUser();
    });
    const c = chip(m.container);
    expect(c?.textContent).toBe("Sample data");
    expect(c?.closest("header.park-nav")).not.toBeNull();
    expect(c?.querySelector(".park-chip")).not.toBeNull(); // the StatusChip component
  });

  it("WEB_3b_nav_a_live_only_session_has_no_chip", async () => {
    const { m } = mountShell(<TopNav />, { api: liveApi() });
    await act(async () => {
      await seen.api.getUser();
      await seen.api.getDecisions();
    });
    expect(seen.store.getState().sources).toEqual({ fixture: false, live: true });
    expect(chip(m.container)).toBeNull();
  });

  it("WEB_3b_nav_the_chip_stays_when_a_live_result_arrives_after_a_fixture_one", async () => {
    const { m } = mountShell(<TopNav />);
    await act(async () => {
      await seen.api.getUser();
    });
    act(() => seen.store.noteSource("live"));
    expect(chip(m.container)?.textContent).toBe("Sample data");
  });

  it("WEB_3b_nav_clicking_the_chip_opens_the_explanation_and_Escape_closes_it", async () => {
    const { m } = mountShell(<TopNav />);
    await act(async () => {
      await seen.api.getUser();
    });
    const c = chip(m.container) as HTMLButtonElement;
    expect(c.getAttribute("aria-expanded")).toBe("false");
    focus(c);
    click(c);
    const dialog = q(document.body, '[role="dialog"][aria-label="Sample data"]');
    expect(dialog.textContent).toContain(SAMPLE);
    expect(c.getAttribute("aria-expanded")).toBe("true");
    pressDocument("Escape");
    expect(document.querySelector('[role="dialog"][aria-label="Sample data"]')).toBeNull();
    expect(document.activeElement).toBe(c);
  });

  it("WEB_3b_nav_the_chip_popover_is_not_one_of_the_two_store_menus", async () => {
    const { m } = mountShell(<TopNav />);
    await act(async () => {
      await seen.api.getUser();
    });
    click(chip(m.container) as HTMLButtonElement);
    expect(seen.store.getState().menu).toBeNull();
  });
});
