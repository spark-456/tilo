// @vitest-environment happy-dom
// FR-ACC-03 (connector detail: account, sync status with a spinner, scopes, "Used by" links) and FR-ACC-04
// (a warning 3 days before a sign-in expires, one-click reconnect, never a password) on the Park Connectors
// page. The clock is a fixed `now` prop (page code reads no Date.now); expiry comes from `Connector.expires`.
import { afterEach, describe, expect, it } from "vitest";
import { fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import {
  type TestApp,
  buttonText,
  connectedTiles,
  flush,
  hasExactText,
  labelled,
  makeApp,
  textOf,
  tileFor,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { createFixtureApi } from "../../api/fixtureApi";
import * as fx from "../../api/fixtures";
import type { Api } from "../../api/index";
import type { Connector, Skill } from "../../api/types";
import { ParkProvider } from "../../app/context";
import { ConnectorsPage } from "./ConnectorsPage";

afterEach(cleanup);

const DAY = 86_400_000;
const NOW = Date.parse("2026-10-08T09:00:00Z");
const iso = (ms: number) => new Date(ms).toISOString();
const ok = <T,>(data: T) =>
  Promise.resolve({ data: structuredClone(data), source: "fixture" as const });

/** The fixture connectors with HubSpot healthy and carrying a real expiry instant. */
function withHubspotExpiry(expiresMs: number | undefined): Connector[] {
  return fx.connectors.map((c) =>
    c.id !== "hubspot"
      ? c
      : {
          ...c,
          st: "connected" as const,
          sync: "2 min ago",
          ...(expiresMs === undefined ? {} : { expires: iso(expiresMs) }),
        },
  );
}

async function open(
  connectors: Connector[],
  over: { skills?: Skill[]; now?: number; app?: TestApp } = {},
) {
  const base = createFixtureApi();
  const api: Api = {
    ...base,
    getConnectors: () => ok(connectors),
    ...(over.skills ? { getSkills: () => ok(over.skills) } : {}),
  } as Api;
  const app = over.app ?? makeApp();
  const sch = fakeScheduler();
  const now = over.now ?? NOW;
  const m = mount(
    <ParkProvider api={api} schedule={sch.schedule} viewport={{ vw: app.vw, vh: app.vh }}>
      <div data-park="" data-time="day">
        <ConnectorsPage app={app} now={() => now} />
      </div>
    </ParkProvider>,
  );
  await flush();
  await waitFor(() => connectedTiles(m.container).length > 0, "the Connected tiles");
  return { app, root: m.container };
}

const dialogOf = (root: HTMLElement) => root.querySelector<HTMLElement>('[role="dialog"]');
function openTile(root: HTMLElement, name: string): HTMLElement {
  click(tileFor(root, name) as HTMLElement);
  return dialogOf(root) as HTMLElement;
}
const banner = (root: HTMLElement) => root.querySelector<HTMLElement>(".park-connectors-banner");
const spinners = (root: ParentNode) => root.querySelectorAll(".park-connectors-spin");

describe("FR_ACC_03 Used by is derived from the skills and worlds that reference the tool", () => {
  it("FR_ACC_03_used_by_lists_a_skill_that_references_the_tool_in_its_tools", async () => {
    const { root } = await open(fx.connectors);
    // "Log new supplier invoices" has Gmail in skill.tools but is not in Gmail's own `used` record.
    const rows = openTile(root, "Gmail");
    expect(buttonText(rows, "Log new supplier invoices")).toBeDefined();
  });

  it("FR_ACC_03_used_by_lists_the_worlds_those_skills_run_in_and_links_to_them", async () => {
    const { app, root } = await open(fx.connectors);
    const d = openTile(root, "Gmail");
    const invoice = fx.worlds({}, []).find((w) => w.id === "invoice");
    expect(invoice, "a fixture world").toBeDefined();
    const row = buttonText(d, invoice?.name ?? "");
    expect(row, "the world row").toBeDefined();
    click(row as HTMLElement);
    expect(app.go.mock.calls.at(-1)).toEqual(["world", { id: "invoice" }]);
    expect(dialogOf(root)).toBeNull();
  });

  it("FR_ACC_03_used_by_follows_the_data_not_a_fixed_list", async () => {
    const skill: Skill = {
      ...(fx.skills[0] as Skill),
      id: "zz-roll-call",
      name: "Zebra roll-call",
      tools: [["Slack", 1]],
      used: [],
    };
    const without = await open(fx.connectors);
    expect(buttonText(openTile(without.root, "Slack"), "Zebra roll-call")).toBeUndefined();
    cleanup();
    const withIt = await open(fx.connectors, { skills: [...fx.skills, skill] });
    const row = buttonText(openTile(withIt.root, "Slack"), "Zebra roll-call");
    expect(row, "a new skill using Slack appears").toBeDefined();
    click(row as HTMLElement);
    expect(withIt.app.go.mock.calls.at(-1)).toEqual(["skills", { id: "zz-roll-call" }]);
  });
});

describe("FR_ACC_03 sync status shows a spinner only while a sync is in flight", () => {
  it("FR_ACC_03_no_spinner_at_rest_anywhere_on_the_page_or_in_the_detail", async () => {
    const { root } = await open(fx.connectors);
    expect(spinners(root).length).toBe(0);
    const d = openTile(root, "Google Drive");
    expect(spinners(d).length).toBe(0);
    expect(hasExactText(d, "Example only · no sync or health check recorded")).toBe(true);
  });

  it("FR_ACC_03_sync_now_shows_a_spinner_and_Syncing_until_the_sync_ends", async () => {
    const { root } = await open(fx.connectors);
    const d = openTile(root, "Google Drive");
    click(buttonText(d, "Sync now") as HTMLElement);
    expect(spinners(d).length, "in flight").toBe(1);
    expect(textOf(d)).toContain("Syncing");
    await flush();
    expect(spinners(d).length, "settled").toBe(0);
    expect(hasExactText(d, "Example only · no sync or health check recorded")).toBe(true);
  });
});

describe("FR_ACC_03 the detail panel never asks for a password", () => {
  it("FR_ACC_03_no_password_or_text_field_in_the_connector_detail", async () => {
    const { root } = await open(fx.connectors);
    for (const name of ["Gmail", "HubSpot"]) {
      const d = openTile(root, name);
      expect(d.querySelectorAll("input, textarea").length, `${name} detail`).toBe(0);
      expect(d.querySelector('[type="password"], [autocomplete*="password"]')).toBeNull();
      click(labelled(root, "Close") as HTMLElement);
    }
  });
});

describe("FR_ACC_04 the sign-in expiry warning shows 3 days ahead", () => {
  it("FR_ACC_04_four_days_ahead_shows_no_warning", async () => {
    const { root } = await open(withHubspotExpiry(NOW + 4 * DAY));
    expect(banner(root)).toBeNull();
    expect(textOf(tileFor(root, "HubSpot") as HTMLElement)).toContain("Example only: not synced");
  });

  it("FR_ACC_04_just_over_three_days_ahead_shows_no_warning", async () => {
    const { root } = await open(withHubspotExpiry(NOW + 3 * DAY + 60_000));
    expect(banner(root)).toBeNull();
  });

  it("FR_ACC_04_exactly_three_days_ahead_shows_the_warning_with_a_reconnect_button", async () => {
    const { root } = await open(withHubspotExpiry(NOW + 3 * DAY));
    const b = banner(root) as HTMLElement;
    expect(b).not.toBeNull();
    expect(textOf(b)).toContain("HubSpot sign-in expires in 3 days");
    expect(buttonText(b, "Reconnect")).toBeDefined();
    expect(textOf(tileFor(root, "HubSpot") as HTMLElement)).toContain("Sign-in expires in 3 days");
  });

  it("FR_ACC_04_the_day_count_follows_the_clock_and_one_day_is_singular", async () => {
    const hs = withHubspotExpiry(NOW + 3 * DAY);
    const later = await open(hs, { now: NOW + 2 * DAY });
    expect(textOf(banner(later.root) as HTMLElement)).toContain("HubSpot sign-in expires in 1 day");
    expect(textOf(banner(later.root) as HTMLElement)).not.toContain("1 days");
  });

  it("FR_ACC_04_an_expired_sign_in_shows_a_stronger_state_than_the_warning", async () => {
    const soon = await open(withHubspotExpiry(NOW + 3 * DAY));
    const soonBanner = banner(soon.root) as HTMLElement;
    expect(soonBanner.getAttribute("role")).not.toBe("alert");
    cleanup();
    const { root } = await open(withHubspotExpiry(NOW - 60 * 60 * 1000));
    const b = banner(root) as HTMLElement;
    expect(textOf(b)).toContain("HubSpot sign-in expired");
    expect(b.getAttribute("role"), "announced at once, and by words not colour").toBe("alert");
    expect(b.className).toContain("park-connectors-banner--expired");
    expect(buttonText(b, "Reconnect"), "still one click away").toBeDefined();
  });

  it("FR_ACC_04_a_connector_with_no_expiry_data_keeps_its_recorded_status", async () => {
    const { root } = await open(fx.connectors);
    expect(textOf(banner(root) as HTMLElement)).toContain("HubSpot sign-in expires in 3 days");
  });
});

describe("FR_ACC_04 reconnect is one click and never shows Tilo a password", () => {
  it("FR_ACC_04_one_click_on_the_banner_reconnects_and_clears_the_warning", async () => {
    const { app, root } = await open(withHubspotExpiry(NOW + 2 * DAY));
    click(buttonText(banner(root) as HTMLElement, "Reconnect") as HTMLElement);
    await waitFor(() => banner(root) === null, "the banner clears");
    expect(app.toast.mock.calls.at(-1)?.[0]).toBe("HubSpot reconnected for 90 days");
    expect(textOf(tileFor(root, "HubSpot") as HTMLElement)).toContain("Example only: not synced");
  });

  it("FR_ACC_04_the_detail_panel_of_an_expiring_tool_has_its_own_one_click_reconnect", async () => {
    const { root } = await open(withHubspotExpiry(NOW + 1 * DAY));
    const d = openTile(root, "HubSpot");
    expect(textOf(d)).toContain("Sign-in expires in 1 day");
    click(buttonText(d, "Reconnect") as HTMLElement);
    await waitFor(() => banner(root) === null, "the banner clears");
    expect(hasExactText(d, "Example only · no sync or health check recorded")).toBe(true);
    expect(buttonText(d, "Reconnect")).toBeUndefined();
  });

  it("FR_ACC_04_no_password_field_anywhere_in_the_reconnect_flow", async () => {
    const { root } = await open(withHubspotExpiry(NOW + 1 * DAY));
    const b = banner(root) as HTMLElement;
    const d = openTile(root, "HubSpot");
    for (const el of [b, d]) {
      expect(el.querySelectorAll("input, textarea").length).toBe(0);
      expect(el.querySelector('[type="password"], [autocomplete*="password"]')).toBeNull();
    }
    expect(textOf(d)).toContain("Tilo never sees your password");
    click(buttonText(d, "Reconnect") as HTMLElement);
    await flush();
    expect(root.querySelectorAll('input[type="password"]').length).toBe(0);
  });
});
