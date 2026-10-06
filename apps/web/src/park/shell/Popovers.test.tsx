// @vitest-environment happy-dom
// WEB-3b: <NotificationsPopover/> and <AccountMenu/> (README "Shell > Notifications popover / Account menu";
// reference `Tilo App.dc.html`). Pinned surface:
//   park/shell/NotificationsPopover.tsx: `NotificationsPopover({ items: readonly Notification[] })`. Renders
//     nothing unless store.menu === "notif"; then the `Popover` component (role dialog, aria-label
//     "Notifications", width 392): a header (`span.park-notif__head-title` "Notifications" and the `button`
//     "Settings"), then one `button.park-notif__row` per item with `span.park-notif__tile`
//     (`park-notif__tile--needs|done|warn`), `span.park-notif__title`, `span.park-notif__sub`,
//     `span.park-notif__time`. A row whose `dec` is approved reads "You approved Laptop Depot" or "You sent the
//     supplier brief" on a done tile. A world row opens the world through store.openWorld (the loader); the
//     HubSpot row goes to /park/connectors; opening closes the menu first. AppShell fetches the items.
//   park/shell/AccountMenu.tsx: `AccountMenu({ user: User })`. Renders nothing unless store.menu === "acct"; then
//     a `div[data-testid="park-account-menu"]` holding the header (`.park-acct__avatar` initials,
//     `.park-acct__name`, `.park-acct__email`, `.park-acct__org` "<org> · <plan> plan"), the separator
//     `.park-acct__sep` and the `Menu` component (role menu, aria-label "Account", width 300).
import { act } from "react";
import { afterEach, describe, expect, it } from "vitest";
import {
  cleanup,
  click,
  focus,
  pressDocument,
  q,
  qa,
} from "../../../test-support/park/componentsHarness";
import { mountShell, seen } from "../../../test-support/park/shellHarness";
import { notifications } from "../api/fixtures/notifications";
import { user } from "../api/fixtures/user";
import { AccountMenu } from "./AccountMenu";
import { NotificationsPopover } from "./NotificationsPopover";
import { TopNav } from "./TopNav";

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const dialog = () => document.querySelector<HTMLElement>('[role="dialog"][aria-label="Notifications"]');
const rows = () => qa<HTMLButtonElement>(document.body, "button.park-notif__row");
const rowOf = (title: string) =>
  rows().find((r) => r.querySelector(".park-notif__title")?.textContent === title) as HTMLButtonElement;
const open = (which: "notif" | "acct") => act(() => seen.store.toggleMenu(which));

describe("WEB_3b_notif: the popover", () => {
  it("WEB_3b_notif_renders_nothing_while_the_menu_is_closed", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    expect(dialog()).toBeNull();
  });

  it("WEB_3b_notif_is_a_named_dialog_392_wide_with_the_header_and_Settings", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    const d = dialog() as HTMLElement;
    expect(d).not.toBeNull();
    expect(d.style.width).toBe("392px");
    expect(q(d, ".park-notif__head-title").textContent).toBe("Notifications");
    const settings = qa<HTMLButtonElement>(d, "button").find((b) => b.textContent === "Settings");
    expect(settings?.getAttribute("type")).toBe("button");
  });

  it("WEB_3b_notif_lists_every_notification_in_order_with_title_sub_and_time", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    expect(rows()).toHaveLength(5);
    expect(
      rows().map((r) => [
        q(r, ".park-notif__title").textContent,
        q(r, ".park-notif__sub").textContent,
        q(r, ".park-notif__time").textContent,
      ]),
    ).toEqual([
      ["Laptop Depot needs budget sign-off", "K1 electric scooter · £3,420", "11:52"],
      ["Supplier brief is waiting at the gate", "K1 electric scooter · 3 suppliers", "11:40"],
      ["Competitor pricing is ready", "Quick task · report", "11:18"],
      ["Draft reply to Northline is ready", "Quick task · draft", "09:40"],
      ["HubSpot sign-in expires in 3 days", "Connectors · reconnect to keep syncing", "Yesterday"],
    ]);
  });

  it("WEB_3b_notif_tiles_carry_the_kind_and_an_icon", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    const tone = (r: Element) =>
      [...q(r, ".park-notif__tile").classList].filter((c) => c.startsWith("park-notif__tile--"));
    expect(rows().map(tone)).toEqual([
      ["park-notif__tile--needs"],
      ["park-notif__tile--needs"],
      ["park-notif__tile--done"],
      ["park-notif__tile--done"],
      ["park-notif__tile--warn"],
    ]);
    for (const r of rows()) expect(q(r, ".park-notif__tile svg")).not.toBeNull();
  });

  it("WEB_3b_notif_an_approved_decision_reads_You_approved_on_a_green_tile", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    act(() => seen.app.decide("depot"));
    const first = rows()[0] as HTMLElement;
    expect(q(first, ".park-notif__title").textContent).toBe("You approved Laptop Depot");
    expect(q(first, ".park-notif__sub").textContent).toBe("K1 electric scooter · £3,420");
    expect(q(first, ".park-notif__tile").classList.contains("park-notif__tile--done")).toBe(true);
    expect(q(rows()[1] as HTMLElement, ".park-notif__title").textContent).toBe(
      "Supplier brief is waiting at the gate",
    );
    act(() => seen.app.decide("mail"));
    const second = rows()[1] as HTMLElement;
    expect(q(second, ".park-notif__title").textContent).toBe("You sent the supplier brief");
    expect(q(second, ".park-notif__tile").classList.contains("park-notif__tile--done")).toBe(true);
  });

  it("WEB_3b_notif_undo_brings_the_waiting_text_back", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    act(() => seen.app.decide("depot"));
    act(() => seen.store.getState().toast?.action?.());
    expect(q(rows()[0] as HTMLElement, ".park-notif__title").textContent).toBe(
      "Laptop Depot needs budget sign-off",
    );
    expect(
      q(rows()[0] as HTMLElement, ".park-notif__tile").classList.contains("park-notif__tile--needs"),
    ).toBe(true);
  });

  it("WEB_3b_notif_a_city_row_opens_the_world_through_the_loader_and_closes_the_menu", () => {
    const { navigate } = mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    click(rowOf("Laptop Depot needs budget sign-off"));
    expect(seen.store.getState().wl).toEqual({ id: "k1", step: 0 });
    expect(seen.store.getState().menu).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
    expect(dialog()).toBeNull();
  });

  it("WEB_3b_notif_a_village_row_opens_its_world_the_same_way", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    click(rowOf("Draft reply to Northline is ready"));
    expect(seen.store.getState().wl).toEqual({ id: "reply", step: 0 });
  });

  it("WEB_3b_notif_the_HubSpot_row_goes_to_Connectors_without_a_loader", () => {
    const { navigate } = mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    click(rowOf("HubSpot sign-in expires in 3 days"));
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith("/park/connectors");
    expect(seen.store.getState().wl).toBeNull();
    expect(seen.store.getState().menu).toBeNull();
  });

  it("WEB_3b_notif_Settings_goes_to_Profile_notifications_and_closes", () => {
    const { navigate } = mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    click(qa<HTMLButtonElement>(dialog() as HTMLElement, "button").find((b) => b.textContent === "Settings") as HTMLButtonElement);
    expect(navigate).toHaveBeenCalledWith("/park/profile?tab=notifications");
    expect(seen.store.getState().menu).toBeNull();
  });

  it("WEB_3b_notif_opening_it_marks_the_notifications_read", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    expect(seen.store.getState().read).toBe(false);
    open("notif");
    expect(seen.store.getState().read).toBe(true);
  });

  it("WEB_3b_notif_Escape_and_a_click_on_the_backdrop_close_it", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("notif");
    pressDocument("Escape");
    expect(seen.store.getState().menu).toBeNull();
    expect(dialog()).toBeNull();
    open("notif");
    click(q(document.body, ".park-popover__backdrop"));
    expect(seen.store.getState().menu).toBeNull();
    expect(dialog()).toBeNull();
  });

  it("WEB_3b_notif_focus_goes_back_to_the_bell_when_it_closes", () => {
    const { m } = mountShell(
      <>
        <TopNav />
        <NotificationsPopover items={notifications} />
      </>,
    );
    const bell = q<HTMLButtonElement>(m.container, 'button[aria-label="Notifications"]');
    focus(bell);
    click(bell);
    expect(document.activeElement).not.toBe(bell);
    pressDocument("Escape");
    expect(document.activeElement).toBe(bell);
  });

  it("WEB_3b_notif_with_no_items_it_still_opens_with_its_header", () => {
    mountShell(<NotificationsPopover items={[]} />);
    open("notif");
    expect(dialog()).not.toBeNull();
    expect(rows()).toHaveLength(0);
  });

  it("WEB_3b_notif_it_does_not_show_while_the_account_menu_is_the_open_one", () => {
    mountShell(<NotificationsPopover items={notifications} />);
    open("acct");
    expect(dialog()).toBeNull();
  });
});

describe("WEB_3b_acct: the account menu", () => {
  const menu = () => document.querySelector<HTMLElement>('[role="menu"][aria-label="Account"]');
  const items = () => qa<HTMLButtonElement>(document.body, '[role="menuitem"]');
  const item = (label: string) =>
    items().find((b) => b.querySelector(".park-menu__label")?.textContent === label) as HTMLButtonElement;

  it("WEB_3b_acct_renders_nothing_while_the_menu_is_closed", () => {
    mountShell(<AccountMenu user={user} />);
    expect(menu()).toBeNull();
    expect(document.querySelector('[data-testid="park-account-menu"]')).toBeNull();
  });

  it("WEB_3b_acct_is_a_named_menu_300_wide", () => {
    mountShell(<AccountMenu user={user} />);
    open("acct");
    expect(menu()).not.toBeNull();
    expect(menu()?.style.width).toBe("300px");
  });

  it("WEB_3b_acct_header_has_initials_name_email_and_org_and_plan", () => {
    mountShell(<AccountMenu user={user} />);
    open("acct");
    const root = q(document.body, '[data-testid="park-account-menu"]');
    expect(q(root, ".park-acct__avatar").textContent).toBe("AM");
    expect(q(root, ".park-acct__name").textContent).toBe("Alex Morgan");
    expect(q(root, ".park-acct__email").textContent).toBe("alex@northwind.co");
    expect(q(root, ".park-acct__org").textContent).toBe("Northwind Ops · Team plan");
    expect(q(root, ".park-acct__sep")).not.toBeNull();
    expect(root.querySelector('[role="menu"]')).not.toBeNull();
  });

  it("WEB_3b_acct_has_the_five_items_in_order_with_their_hints", () => {
    mountShell(<AccountMenu user={user} />);
    open("acct");
    expect(
      items().map((b) => [
        q(b, ".park-menu__label").textContent,
        b.querySelector(".park-menu__hint")?.textContent ?? "",
      ]),
    ).toEqual([
      ["Profile and settings", ""],
      ["Connectors", "6 on"],
      ["Team and roles", ""],
      ["Mobile app", "Concept"],
      ["Sign out", ""],
    ]);
    for (const b of items()) expect(b.querySelector("svg")).not.toBeNull();
  });

  it("WEB_3b_acct_the_three_links_go_to_their_pages_and_close_the_menu", () => {
    for (const [label, path] of [
      ["Profile and settings", "/park/profile"],
      ["Connectors", "/park/connectors"],
      ["Team and roles", "/park/team"],
    ] as const) {
      const { m, navigate } = mountShell(<AccountMenu user={user} />);
      open("acct");
      click(item(label));
      expect(navigate, label).toHaveBeenCalledTimes(1);
      expect(navigate, label).toHaveBeenCalledWith(path);
      expect(seen.store.getState().menu, label).toBeNull();
      expect(menu(), label).toBeNull();
      m.unmount();
    }
  });

  it("WEB_3b_acct_Mobile_app_is_a_placeholder_with_no_navigation_and_no_toast", () => {
    const { navigate } = mountShell(<AccountMenu user={user} />);
    open("acct");
    click(item("Mobile app"));
    expect(navigate).not.toHaveBeenCalled();
    expect(seen.store.getState().toast).toBeNull();
    expect(seen.store.getState().wl).toBeNull();
  });

  it("WEB_3b_acct_Sign_out_toasts_that_this_is_a_prototype_and_stays_put", () => {
    const { navigate } = mountShell(<AccountMenu user={user} />);
    open("acct");
    click(item("Sign out"));
    expect(seen.store.getState().toast?.message).toBe("This is a prototype, so you stay signed in");
    expect(seen.store.getState().toast?.actionLabel).toBeUndefined();
    expect(seen.store.getState().menu).toBeNull();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("WEB_3b_acct_Escape_and_the_backdrop_close_it_and_focus_returns_to_the_avatar", () => {
    const { m } = mountShell(
      <>
        <TopNav />
        <AccountMenu user={user} />
      </>,
    );
    const avatar = q<HTMLButtonElement>(m.container, 'button[aria-label="Account menu"]');
    focus(avatar);
    click(avatar);
    expect(menu()).not.toBeNull();
    pressDocument("Escape");
    expect(menu()).toBeNull();
    expect(document.activeElement).toBe(avatar);
    click(avatar);
    click(q(document.body, ".park-popover__backdrop"));
    expect(menu()).toBeNull();
    expect(seen.store.getState().menu).toBeNull();
  });

  it("WEB_3b_acct_arrow_keys_move_between_the_five_rows", () => {
    mountShell(<AccountMenu user={user} />);
    open("acct");
    expect(document.activeElement).toBe(items()[0]);
    act(() => {
      items()[0]?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true }));
    });
    expect(document.activeElement).toBe(items()[1]);
  });
});
