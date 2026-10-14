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
/** The demo's honest toast: the action ran no OAuth and changed nothing (W6). */
const SAMPLE = (tool: string, what: string) =>
  `Sample data: ${tool} was not ${what}. Sign in to use your own tools.`;
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
    expect(hasExactText(d, "Example only · no sync or health check recorded")).toBe(true);
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
    expect(
      hasExactText(
        openTile(root, "Google Calendar"),
        "Example only · no sync or health check recorded",
      ),
    ).toBe(true);
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

  it("W6_connectors_demo_drawer_picking_a_level_changes_nothing_and_says_so", async () => {
    const { app, root } = await open();
    const d = openTile(root, "Gmail");
    const before = radios(d).map((r) => r.getAttribute("aria-checked"));
    const tile = textOf(tileFor(root, "Gmail") as HTMLElement);
    click(radios(d)[1] as HTMLElement);
    toastCopy(app, SAMPLE("Gmail", "changed"));
    expect(radios(d).map((r) => r.getAttribute("aria-checked"))).toEqual(before);
    expect(textOf(tileFor(root, "Gmail") as HTMLElement)).toBe(tile);
  });

  it("W6_connectors_demo_drawer_sync_now_says_nothing_was_synced_and_keeps_the_drawer_open", async () => {
    const { app, root } = await open();
    const d = openTile(root, "Google Drive");
    click(buttonText(d, "Sync now") as HTMLElement);
    toastCopy(app, SAMPLE("Google Drive", "synced"));
    expect(textOf(d)).not.toContain("Syncing");
    expect(dialogOf(root)).not.toBeNull();
  });

  it("W6_connectors_demo_drawer_disconnect_says_nothing_was_disconnected_and_keeps_the_tool", async () => {
    const { app, root } = await open();
    const d = openTile(root, "Gmail");
    click(buttonText(d, "Disconnect") as HTMLElement);
    expect(dialogOf(root)).toBeNull();
    toastCopy(app, SAMPLE("Gmail", "disconnected"));
    expect(tileFor(root, "Gmail")).toBeDefined();
    expect(connectedTiles(root)).toHaveLength(6);
    expect(connectButtons(root)).toHaveLength(6);
    expect(countExactText(root, "6 connected")).toBe(2);
  });

  it("W6_connectors_demo_disconnecting_hubspot_keeps_the_attention_banner", async () => {
    const { root } = await open();
    click(buttonText(openTile(root, "HubSpot"), "Disconnect") as HTMLElement);
    expect(hasExactText(root, "HubSpot sign-in expires in 3 days")).toBe(true);
    expect(tileFor(root, "HubSpot")).toBeDefined();
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

describe("W6_connectors_demo_connect: no OAuth runs, so nothing is shown or announced as connected", () => {
  it("W6_connectors_demo_connect_says_nothing_was_connected_and_the_lists_stay_as_loaded", async () => {
    const { app, root } = await open();
    click(connectButtons(root)[0] as HTMLElement);
    await flush();
    toastCopy(app, SAMPLE("Notion", "connected"));
    expect(tileFor(root, "Notion")).toBeUndefined();
    expect(textOf(connectButtons(root)[0] as HTMLElement)).not.toBe("Signing in");
    expect(connectedTiles(root)).toHaveLength(6);
    expect(connectButtons(root)).toHaveLength(6);
    expect(countExactText(root, "6 connected")).toBe(2);
    expect(textOf(root)).not.toContain("Connected just now");
    expect(app.go, "an in-page sign-in, not a navigation").not.toHaveBeenCalled();
    expect(app.decide).not.toHaveBeenCalled();
  });

  it("W6_connectors_demo_connect_toasts_at_once_without_any_timer", async () => {
    const { app, root } = await open();
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "requestAnimationFrame"] });
    click(connectButtons(root)[0] as HTMLElement);
    toastCopy(app, SAMPLE("Notion", "connected"));
  });
});

describe("W6_connectors_demo_reconnect: the HubSpot banner stays until a real sign-in", () => {
  const reconnect = (root: HTMLElement) =>
    [...root.querySelectorAll("button")].find((b) => /^Reconnect$/.test(textOf(b))) as
      | HTMLButtonElement
      | undefined;

  it("W6_connectors_demo_reconnect_says_nothing_was_reconnected_and_keeps_the_banner", async () => {
    const { app, root } = await open();
    click(reconnect(root) as HTMLElement);
    await flush();
    expect(textOf(reconnect(root) as HTMLElement)).toBe("Reconnect");
    expect(app.toast).toHaveBeenCalledTimes(1);
    toastCopy(app, SAMPLE("HubSpot", "reconnected"));
    expect(hasExactText(root, "HubSpot sign-in expires in 3 days")).toBe(true);
    expect(textOf(tileFor(root, "HubSpot") as HTMLElement)).toContain("Sign-in expires");
    expect(countExactText(root, "6 connected")).toBe(2);
    expect(app.go, "S-08 hand-off is not in the design").not.toHaveBeenCalled();
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
    click(buttonText(root, "Reconnect") as HTMLElement);
    click(buttonText(openTile(root, "Xero"), "Disconnect") as HTMLElement);
    await act(async () => undefined);
    expect(err.mock.calls).toEqual([]);
    expect(warn.mock.calls).toEqual([]);
  });
});
