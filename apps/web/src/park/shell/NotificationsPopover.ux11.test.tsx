// @vitest-environment happy-dom
// FR-UX-11 (docs/prd-supplement-design-2026-10-06.md row FR-UX-11): "Bell with unread dot; approved items
// turn into 'You approved'. Each notification opens its world, Connectors or Settings."
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import {
  cleanup,
  click,
  focus,
  pressDocument,
  q,
  qa,
} from "../../../test-support/park/componentsHarness";
import { mountApp, seen } from "../../../test-support/park/shellHarness";
import type { Decision, Notification } from "../api/types";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

const bell = () => q<HTMLButtonElement>(document.body, 'button[aria-label="Notifications"]');
const unreadDots = () => [...bell().children].filter((c) => c.tagName.toLowerCase() !== "svg");
const dialog = () =>
  document.querySelector<HTMLElement>('[role="dialog"][aria-label="Notifications"]');
const rows = () => qa<HTMLButtonElement>(dialog() as HTMLElement, "button[data-kind]");
const settings = () =>
  qa<HTMLButtonElement>(dialog() as HTMLElement, "button").find(
    (b) => b.textContent === "Settings",
  ) as HTMLButtonElement;
const rowWith = (text: string) =>
  rows().find((r) => (r.textContent ?? "").includes(text)) as HTMLButtonElement;

describe("FR_UX_11 notifications popover", () => {
  it("test_FR_UX_11_bell_shows_unread_dot_only_when_something_is_unread", async () => {
    await mountApp();
    expect(unreadDots()).toHaveLength(1);
    act(() => seen.app.decide("depot"));
    expect(unreadDots()).toHaveLength(1);
    act(() => seen.app.decide("mail"));
    expect(seen.store.getState().read).toBe(false);
    expect(unreadDots()).toHaveLength(0);

    // Undoing brings back the waiting decision and the unread dot if never opened
    act(() => seen.store.getState().toast?.action?.());
    expect(unreadDots()).toHaveLength(1);

    // Opening the bell marks notifications read and removes the dot permanently
    click(bell());
    expect(unreadDots()).toHaveLength(0);
    click(bell());
    expect(unreadDots()).toHaveLength(0);
  });

  it("test_FR_UX_11_opening_bell_lists_notifications_at_390x844_and_1440x900", async () => {
    for (const viewport of [
      { vw: 390, vh: 844 },
      { vw: 1440, vh: 900 },
    ] as const) {
      const { m } = await mountApp({ viewport });
      expect(dialog()).toBeNull();
      click(bell());
      expect(dialog()).not.toBeNull();
      expect(seen.app.vw).toBe(viewport.vw);
      expect(seen.app.vh).toBe(viewport.vh);
      expect(rows().map((r) => r.textContent)).toEqual([
        "Laptop Depot needs budget sign-offK1 electric scooter · £3,42011:52",
        "Supplier brief is waiting at the gateK1 electric scooter · 3 suppliers11:40",
        "Competitor pricing is readyQuick task · report11:18",
        "Draft reply to Northline is readyQuick task · draft09:40",
        "HubSpot sign-in expires in 3 daysConnectors · reconnect to keep syncingYesterday",
      ]);
      m.unmount();
    }
  });

  it("test_FR_UX_11_approved_card_renders_You_approved_including_fallback_without_approvedTitle", async () => {
    const api = fakeApi();
    const customDecisions: Decision[] = [
      {
        k: "depot",
        world: "k1",
        title: "Budget sign-off",
        body: "Needs sign-off",
        yes: "Approve",
        icon: "coin",
        done: "Approved · just now",
        toast: "",
        approvedTitle: "",
      },
      {
        k: "mail",
        world: "k1",
        title: "Supplier brief",
        body: "Brief waiting",
        yes: "Send brief",
        icon: "mail",
        done: "Sent · just now",
        toast: "Supplier brief sent to 3 suppliers",
        approvedTitle: "You sent the supplier brief",
      },
    ];
    const customNotifications: Notification[] = [
      {
        id: "n1",
        t: "11:52",
        title: "Budget sign-off waiting",
        sub: "Project · £3,420",
        kind: "needs",
        go: ["world", "k1"],
        dec: "depot",
      },
      {
        id: "n2",
        t: "11:40",
        title: "Supplier brief waiting",
        sub: "Project · 3 suppliers",
        kind: "needs",
        go: ["world", "k1"],
        dec: "mail",
      },
    ];
    vi.spyOn(api, "getDecisions").mockResolvedValue({ data: customDecisions, source: "live" });
    vi.spyOn(api, "getNotifications").mockResolvedValue({
      data: customNotifications,
      source: "live",
    });

    await mountApp({ api });
    click(bell());
    act(() => seen.app.decide("depot"));
    await act(async () => undefined);
    // Even when approvedTitle is blank on a live/custom decision, an approved card renders "You approved"
    expect(rows()[0]?.textContent).toContain("You approved");
    expect(rows()[0]?.getAttribute("data-kind")).toBe("done");

    act(() => seen.app.decide("mail"));
    await act(async () => undefined);
    expect(rows()[1]?.textContent).toContain("You sent the supplier brief");
    expect(rows()[1]?.getAttribute("data-kind")).toBe("done");
  });

  it("test_FR_UX_11_each_item_navigates_to_its_world_Connectors_or_Settings", async () => {
    for (const [text, worldId] of [
      ["Laptop Depot", "k1"],
      ["Supplier brief", "k1"],
      ["Competitor pricing", "comp"],
      ["Draft reply", "reply"],
    ] as const) {
      const { m, navigate, sch } = await mountApp();
      click(bell());
      click(rowWith(text));
      expect(dialog()).toBeNull();
      expect(seen.store.getState().wl).toMatchObject({ id: worldId, step: 0 });
      for (let i = 0; i < 3; i++) act(() => sch.fire(sch.live()[0]));
      expect(navigate).toHaveBeenCalledWith(`/world/${worldId}`);
      m.unmount();
    }

    const { m: mConn, navigate: navConn } = await mountApp();
    click(bell());
    click(rowWith("HubSpot"));
    expect(dialog()).toBeNull();
    expect(navConn).toHaveBeenCalledWith("/connectors");
    mConn.unmount();

    const { m: mSet, navigate: navSet } = await mountApp();
    click(bell());
    click(settings());
    expect(dialog()).toBeNull();
    expect(navSet).toHaveBeenCalledWith("/profile?tab=notifications");
    mSet.unmount();
  });

  it("test_FR_UX_11_Escape_closes_popover_and_focus_returns_to_bell", async () => {
    await mountApp();
    focus(bell());
    click(bell());
    expect(dialog()).not.toBeNull();
    expect(document.activeElement).not.toBe(bell());
    pressDocument("Escape");
    expect(dialog()).toBeNull();
    expect(document.activeElement).toBe(bell());
  });
});
