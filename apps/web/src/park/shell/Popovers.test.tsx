// @vitest-environment happy-dom
// WEB-3b: the notifications popover and the account menu (README "Shell > Notifications popover / Account
// menu"; reference `Tilo App.dc.html`: role dialog "Notifications", role menu "Account", the prototype's
// strings, `go(...)` targets and Sign out toast). Mounted through <AppShell/>; widths, offsets, tile colours
// and the separator are checked against the measured reference in e2e/park-shell-visual.spec.ts.
// Hook the builder must expose: each notification row is a button inside the dialog carrying
// `data-kind="needs|done|warn"` (the kind that picks its tile; it becomes "done" once its decision is approved).
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
import { mountApp, seen } from "../../../test-support/park/shellHarness";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const bell = () => q<HTMLButtonElement>(document.body, 'button[aria-label="Notifications"]');
const avatar = () => q<HTMLButtonElement>(document.body, 'button[aria-label="Account menu"]');
const dialog = () =>
  document.querySelector<HTMLElement>('[role="dialog"][aria-label="Notifications"]');
const rows = () => qa<HTMLButtonElement>(dialog() as HTMLElement, "button[data-kind]");
const settings = () =>
  qa<HTMLButtonElement>(dialog() as HTMLElement, "button").find(
    (b) => b.textContent === "Settings",
  ) as HTMLButtonElement;
const rowWith = (text: string) =>
  rows().find((r) => (r.textContent ?? "").includes(text)) as HTMLButtonElement;
const openBell = () => click(bell());

describe("WEB_3b_notif: the notifications popover", () => {
  it("WEB_3b_notif_nothing_shows_until_the_bell_is_pressed", async () => {
    await mountApp();
    expect(dialog()).toBeNull();
    openBell();
    expect(dialog()).not.toBeNull();
  });

  it("WEB_3b_notif_the_header_says_Notifications_and_has_a_Settings_button", async () => {
    await mountApp();
    openBell();
    expect((dialog() as HTMLElement).textContent).toMatch(/^Notifications/);
    expect(settings().getAttribute("type")).toBe("button");
  });

  it("WEB_3b_notif_lists_the_five_notifications_in_order_each_with_title_sub_and_time", async () => {
    await mountApp();
    openBell();
    expect(rows().map((r) => r.textContent)).toEqual([
      "Laptop Depot needs budget sign-offK1 electric scooter · £3,42011:52",
      "Supplier brief is waiting at the gateK1 electric scooter · 3 suppliers11:40",
      "Competitor pricing is readyQuick task · report11:18",
      "Draft reply to Northline is readyQuick task · draft09:40",
      "HubSpot sign-in expires in 3 daysConnectors · reconnect to keep syncing" + "Yesterday",
    ]);
    for (const r of rows()) expect(r.querySelector("svg")).not.toBeNull(); // the tile's icon
  });

  it("WEB_3b_notif_the_kinds_are_needs_needs_done_done_warn", async () => {
    await mountApp();
    openBell();
    expect(rows().map((r) => r.getAttribute("data-kind"))).toEqual([
      "needs",
      "needs",
      "done",
      "done",
      "warn",
    ]);
  });

  it("WEB_3b_notif_approving_flips_the_row_to_You_approved_with_a_done_tile", async () => {
    await mountApp();
    openBell();
    act(() => seen.app.decide("depot"));
    expect(rows()[0]?.textContent).toBe(
      "You approved Laptop DepotK1 electric scooter · £3,42011:52",
    );
    expect(rows()[0]?.getAttribute("data-kind")).toBe("done");
    expect(rows()[1]?.getAttribute("data-kind")).toBe("needs");
    act(() => seen.app.decide("mail"));
    expect(rows()[1]?.textContent).toBe(
      "You sent the supplier briefK1 electric scooter · 3 suppliers11:40",
    );
    expect(rows()[1]?.getAttribute("data-kind")).toBe("done");
  });

  it("WEB_3b_notif_undo_brings_the_waiting_row_back", async () => {
    await mountApp();
    openBell();
    act(() => seen.app.decide("depot"));
    act(() => seen.store.getState().toast?.action?.());
    expect(rows()[0]?.textContent).toContain("Laptop Depot needs budget sign-off");
    expect(rows()[0]?.getAttribute("data-kind")).toBe("needs");
  });

  it("WEB_3b_notif_a_world_row_opens_that_world_through_the_loader_and_closes_the_popover", async () => {
    const { navigate } = await mountApp();
    openBell();
    click(rowWith("Laptop Depot"));
    expect(seen.store.getState().wl).toMatchObject({ id: "k1", step: 0 });
    expect(seen.store.getState().menu).toBeNull();
    expect(dialog()).toBeNull();
    expect(navigate).not.toHaveBeenCalled(); // the page swaps at step 3
  });

  it("WEB_3b_notif_each_world_row_opens_its_own_world", async () => {
    for (const [text, id] of [
      ["Supplier brief", "k1"],
      ["Competitor pricing", "comp"],
      ["Draft reply", "reply"],
    ] as const) {
      const { m } = await mountApp();
      openBell();
      click(rowWith(text));
      expect(seen.store.getState().wl, text).toMatchObject({ id });
      m.unmount();
    }
  });

  it("WEB_3b_notif_the_HubSpot_row_goes_to_Connectors_with_no_loader", async () => {
    const { navigate } = await mountApp();
    openBell();
    click(rowWith("HubSpot"));
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/connectors");
    expect(seen.store.getState().wl).toBeNull();
    expect(dialog()).toBeNull();
  });

  it("WEB_3b_notif_Settings_goes_to_the_Profile_notifications_tab_and_closes", async () => {
    const { navigate } = await mountApp();
    openBell();
    click(settings());
    expect(navigate).toHaveBeenCalledWith("/profile?tab=notifications");
    expect(dialog()).toBeNull();
  });

  it("WEB_3b_notif_opening_it_marks_the_notifications_read", async () => {
    await mountApp();
    expect(seen.store.getState().read).toBe(false);
    openBell();
    expect(seen.store.getState().read).toBe(true);
  });

  it("WEB_3b_notif_Escape_and_a_click_on_the_backdrop_close_it", async () => {
    await mountApp();
    openBell();
    pressDocument("Escape");
    expect(dialog()).toBeNull();
    expect(seen.store.getState().menu).toBeNull();
    openBell();
    click(q(document.body, ".park-popover__backdrop"));
    expect(dialog()).toBeNull();
    expect(seen.store.getState().menu).toBeNull();
  });

  it("WEB_3b_notif_focus_goes_back_to_the_bell_when_it_closes", async () => {
    await mountApp();
    focus(bell());
    openBell();
    expect(document.activeElement).not.toBe(bell());
    pressDocument("Escape");
    expect(document.activeElement).toBe(bell());
  });

  it("WEB_3b_notif_the_account_menu_replaces_it_rather_than_stacking", async () => {
    await mountApp();
    openBell();
    click(avatar());
    expect(dialog()).toBeNull();
    expect(document.querySelector('[role="menu"][aria-label="Account"]')).not.toBeNull();
  });
});

describe("WEB_3b_acct: the account menu", () => {
  const menu = () => document.querySelector<HTMLElement>('[role="menu"][aria-label="Account"]');
  const items = () => qa<HTMLButtonElement>(menu() as HTMLElement, '[role="menuitem"]');
  const item = (name: string) =>
    items().find((b) => (b.textContent ?? "").startsWith(name)) as HTMLButtonElement;
  const openMenu = () => click(avatar());

  it("WEB_3b_acct_it_opens_from_the_avatar_and_nothing_shows_before", async () => {
    await mountApp();
    expect(menu()).toBeNull();
    openMenu();
    expect(menu()).not.toBeNull();
  });

  it("WEB_3b_acct_the_header_has_initials_name_email_and_org_with_plan", async () => {
    await mountApp();
    openMenu();
    const text = (menu() as HTMLElement).textContent ?? "";
    for (const s of ["AM", "Alex Morgan", "alex@northwind.co", "Northwind Ops · Team plan"]) {
      expect(text, s).toContain(s);
    }
    expect(text.indexOf("Alex Morgan")).toBeLessThan(text.indexOf("Profile and settings"));
  });

  it("WEB_3b_acct_the_seven_items_in_order_with_their_hints_and_icons", async () => {
    await mountApp();
    openMenu();
    expect(items().map((b) => b.textContent)).toEqual([
      "Profile and settings",
      "Connectors6 on",
      "More",
      "Team and roles",
      "Library",
      "Mobile appConcept",
      "Sign out",
    ]);
    for (const b of items()) expect(b.querySelector("svg")).not.toBeNull();
  });

  it("FR_UX_10 WEB_3b_acct_the_three_links_go_to_their_pages_and_close_the_menu", async () => {
    for (const [name, path] of [
      ["Profile and settings", "/profile"],
      ["Connectors", "/connectors"],
      ["Team and roles", "/team"],
      ["More", "/more"],
    ] as const) {
      const { m, navigate } = await mountApp();
      openMenu();
      click(item(name));
      expect(navigate, name).toHaveBeenCalledTimes(1);
      expect(navigate, name).toHaveBeenCalledWith(path);
      expect(menu(), name).toBeNull();
      m.unmount();
    }
  });

  it("WEB_3b_acct_Mobile_app_is_a_placeholder_with_no_navigation_and_no_toast", async () => {
    const { navigate } = await mountApp();
    openMenu();
    click(item("Mobile app"));
    expect(navigate).not.toHaveBeenCalled();
    expect(seen.store.getState().toast).toBeNull();
    expect(seen.store.getState().wl).toBeNull();
  });

  it("WEB_3b_acct_Sign_out_toasts_that_this_is_a_prototype_and_stays_put", async () => {
    const { navigate } = await mountApp();
    openMenu();
    click(item("Sign out"));
    expect(seen.store.getState().toast?.message).toBe("This is a prototype, so you stay signed in");
    expect(seen.store.getState().toast?.actionLabel).toBeUndefined();
    expect(menu()).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("WEB_3b_acct_Escape_and_the_backdrop_close_it_and_focus_goes_back_to_the_avatar", async () => {
    await mountApp();
    focus(avatar());
    openMenu();
    expect(menu()).not.toBeNull();
    pressDocument("Escape");
    expect(menu()).toBeNull();
    expect(document.activeElement).toBe(avatar());
    openMenu();
    click(q(document.body, ".park-popover__backdrop"));
    expect(menu()).toBeNull();
    expect(seen.store.getState().menu).toBeNull();
  });

  it("WEB_3b_acct_arrow_keys_walk_the_items", async () => {
    await mountApp();
    openMenu();
    expect(document.activeElement).toBe(items()[0]);
    act(() => {
      items()[0]?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }),
      );
    });
    expect(document.activeElement).toBe(items()[1]);
  });
});
