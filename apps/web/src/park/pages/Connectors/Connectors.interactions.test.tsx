// @vitest-environment happy-dom
// WEB-11 interactions (plan section 10; design reference `Tilo App Connectors.dc.html`, state
// `{ q, open, st, lvl, busy, re }`; inventory.md toasts). Navigation only through app.go, approvals only
// through app.decide (Connectors has none), toasts through app.toast with the design's exact copy.
//
// What the design does, and what is pinned here (defaults listed in the WEB-11 report):
// - Connect and Reconnect are in-page sign-ins, not a navigation: the button reads "Signing in" /
//   "Waiting for HubSpot" while it waits, then the tool moves to Connected with Read access (Reconnect:
//   the HubSpot attention state clears) and a toast follows. Plan section 3 says S-08 opens from
//   "Connect" and "Reconnect"; the design has no such call, so app.go is NOT called here and the S-08
//   consent hand-off is a live-mode follow-up (the shell's job once the Api has a connect endpoint).
// - The design waits with setTimeout (1.4 s, 1.5 s). Page code may hold no timer until WEB-3b, so the wait
//   is an awaited step: the completion must not depend on any timer (checked with fake timers). ParkProvider's
//   `schedule` is the store's seam (toast, page transition); WEB-3a exposes it to pages through no hook
//   (useApp, useParkApi, useParkStore only), so the tests pin the awaited step, not a scheduled one.
// - The design sends every "Used by" name that is not a skill to the Agenda (go("agenda"), no params).
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import {
  type TestApp,
  buttonText,
  connectButtons,
  connectedTiles,
  countExactText,
  flush,
  hasExactText,
  labelled,
  makeApp,
  renderPage,
  textOf,
  tileFor,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { connectors, skills } from "../../api/fixtures";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function open() {
  const app = makeApp();
  const m = await renderPage(app);
  await waitFor(() => connectedTiles(m.container).length > 0, "the Connected tiles");
  return { app, m, root: m.container };
}
const dialogOf = (root: HTMLElement) => root.querySelector<HTMLElement>('[role="dialog"]');
function openTile(root: HTMLElement, name: string): HTMLElement {
  click(tileFor(root, name) as HTMLElement);
  const d = dialogOf(root);
  expect(d, `${name} opens a dialog`).not.toBeNull();
  return d as HTMLElement;
}
const radios = (d: HTMLElement) => [...d.querySelectorAll<HTMLElement>('[role="radio"]')];
const lastToast = (app: TestApp) => app.toast.mock.calls.at(-1);
const toastCopy = (app: TestApp, msg: string) => {
  const call = lastToast(app);
  expect(call?.[0]).toBe(msg);
  expect(call?.[1], "the design's toast has no action").toBeUndefined();
};

describe("WEB_11_connectors_drawer: a tile opens the detail panel", () => {
  it("FR_ACC_03_WEB_11_connectors_drawer_gmail_header_status_levels_and_footer_copy", async () => {
    const { root } = await open();
    const d = openTile(root, "Gmail");
    expect(d.getAttribute("aria-label")).toBe("Gmail");
    expect(hasExactText(d, "Gmail")).toBe(true);
    expect(hasExactText(d, "Email · alex@northwind.co")).toBe(true);
    expect(hasExactText(d, "Healthy · synced 2 min ago")).toBe(true);
    expect(hasExactText(d, "How far agents can go")).toBe(true);
    expect(hasExactText(d, "Used by")).toBe(true);
    expect(
      hasExactText(
        d,
        "Access uses the tool’s own sign-in. You can revoke it here or from Gmail at any time. Team rules for spend and sharing still apply on top.",
      ),
    ).toBe(true);
    expect(buttonText(d, "Disconnect")).toBeDefined();
    expect(buttonText(d, "Sync now")).toBeDefined();
    expect(labelled(d, "Close")?.tagName).toBe("BUTTON");
    const rs = radios(d);
    expect(rs).toHaveLength(3);
    const gmail = connectors.find((c) => c.id === "gmail");
    (gmail?.scopes ?? []).forEach(([sub, lv], i) => {
      const t = textOf(rs[i] as HTMLElement);
      expect(t.startsWith(["", "Read", "Draft", "Act"][lv] as string)).toBe(true);
      expect(t).toContain(sub);
      expect(rs[i]?.getAttribute("aria-checked")).toBe(String(gmail?.level === lv));
    });
  });

  it("FR_ACC_03_WEB_11_connectors_drawer_live_and_attention_status_lines", async () => {
    const { root } = await open();
    expect(hasExactText(openTile(root, "Google Calendar"), "Healthy · synced live")).toBe(true);
    click(labelled(root, "Close") as HTMLElement);
    expect(dialogOf(root)).toBeNull();
    const hub = openTile(root, "HubSpot");
    expect(hasExactText(hub, "Sign-in expires in 3 days. Reconnect to keep agents working.")).toBe(
      true,
    );
    expect(hasExactText(hub, "CRM · Northwind sales")).toBe(true);
  });

  it("WEB_11_connectors_drawer_close_button_closes_it", async () => {
    const { root } = await open();
    openTile(root, "Xero");
    click(labelled(root, "Close") as HTMLElement);
    expect(dialogOf(root)).toBeNull();
  });

  it("WEB_11_connectors_drawer_picking_a_level_selects_it_toasts_and_updates_the_tile", async () => {
    const { app, root } = await open();
    const d = openTile(root, "Gmail");
    click(radios(d)[1] as HTMLElement);
    toastCopy(app, "Gmail: agents can now write drafts");
    expect(radios(d).map((r) => r.getAttribute("aria-checked"))).toEqual([
      "false",
      "true",
      "false",
    ]);
    expect(textOf(tileFor(root, "Gmail") as HTMLElement)).toContain("Draft");
    click(radios(d)[0] as HTMLElement);
    toastCopy(app, "Gmail: agents can now read mail");
    expect(textOf(tileFor(root, "Gmail") as HTMLElement)).toContain("Read");
  });

  it("WEB_11_connectors_drawer_sync_now_toasts_and_keeps_the_drawer_open", async () => {
    const { app, root } = await open();
    const d = openTile(root, "Google Drive");
    click(buttonText(d, "Sync now") as HTMLElement);
    toastCopy(app, "Syncing Google Drive…");
    expect(dialogOf(root)).not.toBeNull();
  });

  it("WEB_11_connectors_drawer_disconnect_closes_toasts_and_moves_the_tool_to_add_a_tool", async () => {
    const { app, root } = await open();
    const d = openTile(root, "Gmail");
    click(buttonText(d, "Disconnect") as HTMLElement);
    expect(dialogOf(root)).toBeNull();
    toastCopy(app, "Gmail disconnected. Skills that use it will pause");
    expect(tileFor(root, "Gmail")).toBeUndefined();
    expect(connectedTiles(root)).toHaveLength(5);
    expect(connectButtons(root)).toHaveLength(7);
    expect(textOf(labelled(root, "Available") as HTMLElement)).toContain("Gmail");
    expect(countExactText(root, "5 connected")).toBe(2);
  });

  it("WEB_11_connectors_drawer_disconnecting_hubspot_clears_the_attention_banner", async () => {
    const { root } = await open();
    click(buttonText(openTile(root, "HubSpot"), "Disconnect") as HTMLElement);
    expect(hasExactText(root, "HubSpot sign-in expires in 3 days")).toBe(false);
    expect(tileFor(root, "HubSpot")).toBeUndefined();
  });
});

describe("WEB_11_connectors_go: Used by sends people to skills or the Agenda", () => {
  const goArgs = (app: TestApp) => app.go.mock.calls.at(-1);

  it("FR_ACC_03_WEB_11_connectors_go_a_skill_name_opens_skills_with_its_id_and_closes_the_drawer", async () => {
    const { app, root } = await open();
    for (const name of ["Triage the Accounts inbox", "Draft a supplier brief"]) {
      const d = openTile(root, "Gmail");
      const skill = skills.find((s) => s.name === name);
      expect(skill, `${name} is a fixture skill`).toBeDefined();
      app.go.mockClear();
      click(buttonText(d, name) as HTMLElement);
      expect(goArgs(app)).toEqual(["skills", { id: skill?.id }]);
      expect(dialogOf(root)).toBeNull();
    }
  });

  it("WEB_11_connectors_go_a_name_that_is_not_a_skill_opens_the_agenda_without_params", async () => {
    const { app, root } = await open();
    const d = openTile(root, "Google Calendar");
    click(buttonText(d, "Find a time") as HTMLElement);
    expect(app.go).toHaveBeenCalledTimes(1);
    expect(goArgs(app)?.[0]).toBe("agenda");
    expect(goArgs(app)?.[1]).toBeUndefined();
    expect(dialogOf(root)).toBeNull();
  });

  it("FR_ACC_03_WEB_11_connectors_go_hubspot_used_by_scan_competitor_prices_opens_that_skill", async () => {
    const { app, root } = await open();
    const d = openTile(root, "HubSpot");
    click(buttonText(d, "Scan competitor prices") as HTMLElement);
    expect(goArgs(app)).toEqual([
      "skills",
      { id: skills.find((s) => s.name === "Scan competitor prices")?.id },
    ]);
  });
});

describe("WEB_11_connectors_connect: Add a tool signs in, then lists the tool as connected", () => {
  it("WEB_11_connectors_connect_waits_as_Signing_in_then_connects_with_Read_access", async () => {
    const { app, root } = await open();
    click(connectButtons(root)[0] as HTMLElement);
    const busy = connectButtons(root)[0] as HTMLButtonElement;
    expect(textOf(busy)).toBe("Signing in");
    expect(busy.disabled).toBe(true);
    await waitFor(() => tileFor(root, "Notion") !== undefined, "Notion in Connected");
    toastCopy(app, "Notion connected with Read access");
    const t = textOf(tileFor(root, "Notion") as HTMLElement);
    expect(t).toContain("Connected just now");
    expect(t).toContain("Read");
    expect(t).toContain("Synced just now");
    expect(t).toContain("Not used yet");
    expect(connectButtons(root)).toHaveLength(5);
    expect(countExactText(root, "7 connected")).toBe(2);
    expect(app.go, "an in-page sign-in, not a navigation").not.toHaveBeenCalled();
    expect(app.decide).not.toHaveBeenCalled();
  });

  it("WEB_11_connectors_connect_a_newly_connected_tool_opens_a_drawer_with_read_selected", async () => {
    const { root } = await open();
    click(connectButtons(root)[0] as HTMLElement);
    await waitFor(() => tileFor(root, "Notion") !== undefined, "Notion in Connected");
    const d = openTile(root, "Notion");
    expect(hasExactText(d, "Healthy · synced just now")).toBe(true);
    expect(radios(d).map((r) => r.getAttribute("aria-checked"))).toEqual([
      "true",
      "false",
      "false",
    ]);
  });

  it("WEB_11_connectors_connect_completes_without_any_timer", async () => {
    const { app, root } = await open();
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "requestAnimationFrame"] });
    click(connectButtons(root)[0] as HTMLElement);
    await flush(100);
    expect(
      tileFor(root, "Notion"),
      "no setTimeout may stand between click and result",
    ).toBeDefined();
    toastCopy(app, "Notion connected with Read access");
  });
});

describe("WEB_11_connectors_reconnect: the HubSpot banner", () => {
  const reconnect = (root: HTMLElement) =>
    [...root.querySelectorAll("button")].find((b) =>
      /^(Reconnect|Waiting for HubSpot)$/.test(textOf(b)),
    ) as HTMLButtonElement | undefined;

  it("FR_ACC_04_WEB_11_connectors_reconnect_waits_ignores_a_second_click_then_clears_the_attention", async () => {
    const { app, root } = await open();
    click(reconnect(root) as HTMLElement);
    expect(textOf(reconnect(root) as HTMLElement)).toBe("Waiting for HubSpot");
    click(reconnect(root) as HTMLElement);
    await waitFor(
      () => !hasExactText(root, "HubSpot sign-in expires in 3 days"),
      "the banner clears",
    );
    expect(app.toast).toHaveBeenCalledTimes(1);
    toastCopy(app, "HubSpot reconnected for 90 days");
    const hub = textOf(tileFor(root, "HubSpot") as HTMLElement);
    expect(hub).toContain("Synced just now");
    expect(hub).not.toContain("Sign-in expires");
    expect(countExactText(root, "6 connected")).toBe(2);
    expect(app.go, "S-08 hand-off is not in the design").not.toHaveBeenCalled();
  });

  it("FR_ACC_04_WEB_11_connectors_reconnect_completes_without_any_timer", async () => {
    const { app, root } = await open();
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "requestAnimationFrame"] });
    click(reconnect(root) as HTMLElement);
    await flush(100);
    expect(hasExactText(root, "HubSpot sign-in expires in 3 days")).toBe(false);
    toastCopy(app, "HubSpot reconnected for 90 days");
  });
});

describe("WEB_11_connectors_console: a whole visit logs no console error or warning", () => {
  it("WEB_11_connectors_console_no_error_or_warning_through_every_interaction", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { root } = await open();
    const d = openTile(root, "Slack");
    click(radios(d)[2] as HTMLElement);
    click(buttonText(d, "Sync now") as HTMLElement);
    click(labelled(root, "Close") as HTMLElement);
    click(connectButtons(root)[1] as HTMLElement);
    await waitFor(() => tileFor(root, "Microsoft 365") !== undefined, "Microsoft 365 connected");
    click(buttonText(root, "Reconnect") as HTMLElement);
    await waitFor(() => !hasExactText(root, "HubSpot sign-in expires in 3 days"), "banner clears");
    click(buttonText(openTile(root, "Xero"), "Disconnect") as HTMLElement);
    await act(async () => undefined);
    expect(err.mock.calls).toEqual([]);
    expect(warn.mock.calls).toEqual([]);
  });
});
