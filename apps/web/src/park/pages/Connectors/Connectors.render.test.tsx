// @vitest-environment happy-dom
// WEB-11 render, copy and search (plan section 10; README "Connectors"; inventory.md "Tilo App
// Connectors.dc.html"; design reference `Tilo App Connectors.dc.html`). Data comes only through the Park
// Api, here the fixture Api, so every tile is checked against the typed fixtures, not retyped by hand.
//
// Defaults taken where the sources are silent (listed in the WEB-11 report):
// - The Api has no connector write (README lists "connector reconnect/sync" as a server call to add), so
//   connect, reconnect, level and disconnect are page-local state, as in the design (`st`, `lvl`).
// - Fixture mode keeps the "Sample data" chip next to the title and the line "Sample data recorded for the
//   demo, not your workspace" (plan 6.1); the shell's own chip is not under test here.
// - The design has no empty state for an empty search, so none is pinned: the counts say "0 connected".
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  connectButtons,
  connectedTiles,
  countExactText,
  flush,
  hasExactText,
  labelled,
  renderPage,
  textOf,
  tileFor,
  typeInto,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { connectors } from "../../api/fixtures";
import { testApp } from "./testApp";

afterEach(cleanup);

const LV = ["", "Read", "Draft", "Act"];
const on = connectors.filter((c) => c.st === "connected" || c.st === "attention");
const avail = connectors.filter((c) => c.st === "available");

async function open() {
  const app = testApp();
  const m = await renderPage(app);
  await waitFor(() => connectedTiles(m.container).length > 0, "the Connected tiles");
  return { app, m, root: m.container };
}

describe("WEB_11_connectors_render: every designed element", () => {
  it("WEB_11_connectors_render_heading_subtitle_search_and_both_regions", async () => {
    const { root } = await open();
    const h1 = root.querySelector("h1");
    expect(h1 && textOf(h1)).toBe("Connectors");
    expect(root.querySelectorAll("h1")).toHaveLength(1);
    const search = labelled(root, "Search connectors");
    expect(search?.tagName).toBe("INPUT");
    expect(search?.getAttribute("placeholder")).toBe("Search 60+ tools");
    expect(labelled(root, "Connected")).not.toBeNull();
    expect(labelled(root, "Available")).not.toBeNull();
    // PageSheet with the design's 22px gap: the default of .park-sheet or an explicit gap of 22.
    const sheets = root.querySelectorAll<HTMLElement>(".park-sheet");
    expect(sheets).toHaveLength(1);
    expect(["", "22px"]).toContain(sheets[0]?.style.gap ?? "");
  });

  it("WEB_11_connectors_render_one_tile_per_connected_fixture_in_fixture_order", async () => {
    const { root } = await open();
    const tiles = connectedTiles(root);
    expect(on).toHaveLength(6);
    expect(tiles).toHaveLength(on.length);
    on.forEach((c, i) => {
      const t = textOf(tiles[i] as HTMLElement);
      const level = LV[c.level ?? 1] as string;
      const sync = c.st === "attention" ? c.sync : `Synced ${c.sync === "Live" ? "live" : c.sync}`;
      expect(t.startsWith(c.mono), `${c.name} monogram (BQ-WEB-1: monograms stay)`).toBe(true);
      expect(t, `${c.name} name`).toContain(c.name);
      expect(t, `${c.name} account`).toContain(c.acct ?? "");
      expect(t, `${c.name} level chip`).toContain(level);
      expect(t, `${c.name} sync line`).toContain(sync as string);
      expect(t, `${c.name} used by`).toContain(`Used by ${c.used?.length ?? 0}`);
    });
  });

  it("WEB_11_connectors_render_literal_spot_checks_of_the_first_and_the_attention_tile", async () => {
    const { root } = await open();
    const gmail = textOf(tileFor(root, "Gmail") as HTMLElement);
    for (const s of ["alex@northwind.co", "Act", "Synced 2 min ago", "Used by 3"]) {
      expect(gmail).toContain(s);
    }
    const cal = textOf(tileFor(root, "Google Calendar") as HTMLElement);
    expect(cal).toContain("Synced live");
    const hub = textOf(tileFor(root, "HubSpot") as HTMLElement);
    expect(hub).toContain("Northwind sales");
    expect(hub).toContain("Read");
    expect(hub).toContain("Sign-in expires in 3 days");
    expect(hub).not.toContain("Synced");
  });

  it("WEB_11_connectors_render_add_a_tool_rows_for_every_available_fixture", async () => {
    const { root } = await open();
    const region = labelled(root, "Available") as HTMLElement;
    const buttons = connectButtons(root);
    expect(avail).toHaveLength(6);
    expect(buttons).toHaveLength(avail.length);
    for (const c of avail) {
      const t = textOf(region);
      expect(t, c.name).toContain(c.name);
      expect(t, `${c.name} blurb`).toContain(c.blurb as string);
      expect(hasExactText(region, c.mono), `${c.name} monogram`).toBe(true);
    }
    for (const b of buttons) expect(textOf(b)).toBe("Connect");
  });

  it("WEB_11_connectors_render_attention_banner_for_hubspot_with_a_reconnect_button", async () => {
    const { root } = await open();
    expect(hasExactText(root, "HubSpot sign-in expires in 3 days")).toBe(true);
    expect(
      hasExactText(
        root,
        "Scan competitor prices reads contacts from it. Reconnect to keep it running.",
      ),
    ).toBe(true);
    const reconnect = [...root.querySelectorAll("button")].filter((b) => textOf(b) === "Reconnect");
    expect(reconnect).toHaveLength(1);
  });

  it("WEB_11_connectors_render_no_drawer_until_a_tile_is_opened", async () => {
    const { root } = await open();
    expect(root.querySelector('[role="dialog"]')).toBeNull();
  });

  it("WEB_11_connectors_render_one_filled_primary_button_at_most_UX_1", async () => {
    const { root } = await open();
    expect(root.querySelectorAll("button.park-btn--primary").length).toBeLessThanOrEqual(1);
  });
});

describe("WEB_11_connectors_copy: verbatim from inventory.md", () => {
  it("WEB_11_connectors_copy_static_strings", async () => {
    const { root } = await open();
    for (const s of [
      "Connectors",
      "The tools your agents can use, and how far each one can go.",
      "HubSpot sign-in expires in 3 days",
      "Scan competitor prices reads contacts from it. Reconnect to keep it running.",
      "Connected",
      "Add a tool",
      "Sign in with the tool. Tilo never sees your password.",
    ]) {
      expect(hasExactText(root, s), `"${s}"`).toBe(true);
    }
  });

  it("WEB_11_connectors_copy_count_reads_6_connected_beside_the_title_and_the_section", async () => {
    const { root } = await open();
    expect(countExactText(root, "6 connected")).toBe(2);
  });
});

describe("WEB_11_connectors_search: filters both sections by name and category", () => {
  const search = (root: HTMLElement) => labelled(root, "Search connectors") as HTMLInputElement;
  const names = (root: HTMLElement) => ({
    on: connectedTiles(root).map((t) => textOf(t)),
    connect: connectButtons(root).length,
    region: textOf(labelled(root, "Available") as HTMLElement),
  });

  it("WEB_11_connectors_search_by_name_is_case_insensitive_and_updates_the_count", async () => {
    const { root } = await open();
    typeInto(search(root), "XERO");
    await flush();
    const r = names(root);
    expect(r.on).toHaveLength(1);
    expect(r.on[0]).toContain("Xero");
    expect(r.connect).toBe(0);
    expect(countExactText(root, "1 connected")).toBe(2);
  });

  it("WEB_11_connectors_search_matches_the_category_too", async () => {
    const { root } = await open();
    typeInto(search(root), "crm");
    await flush();
    expect(names(root).on).toHaveLength(1);
    expect(names(root).on[0]).toContain("HubSpot");
    typeInto(search(root), "payments");
    await flush();
    const r = names(root);
    expect(r.on).toHaveLength(0);
    expect(r.connect).toBe(1);
    expect(r.region).toContain("Stripe");
    expect(countExactText(root, "0 connected")).toBe(2);
  });

  it("WEB_11_connectors_search_does_not_hide_the_attention_banner_and_clearing_restores_all", async () => {
    const { root } = await open();
    typeInto(search(root), "slack");
    await flush();
    expect(hasExactText(root, "HubSpot sign-in expires in 3 days")).toBe(true);
    typeInto(search(root), "");
    await flush();
    expect(names(root).on).toHaveLength(6);
    expect(names(root).connect).toBe(6);
    expect(countExactText(root, "6 connected")).toBe(2);
  });
});

describe("WEB_11_connectors_honesty: fixture data is labelled, statuses come from data", () => {
  it("WEB_11_connectors_honesty_sample_data_chip_and_line_are_shown_in_fixture_mode", async () => {
    const { root } = await open();
    expect(countExactText(root, "Sample data")).toBeGreaterThanOrEqual(1);
    expect(hasExactText(root, "Sample data recorded for the demo, not your workspace")).toBe(true);
    const h1 = root.querySelector("h1") as HTMLElement;
    const chip = [...root.querySelectorAll("*")].find((el) => textOf(el) === "Sample data");
    expect(chip, "the chip is on the page, not hidden by display:none").toBeDefined();
    expect((chip as HTMLElement).hidden).toBe(false);
    // Next to the title: the closest element holding both is in the header, not the whole sheet.
    let common: Element | null = h1;
    while (common && !common.contains(chip as Element)) common = common.parentElement;
    expect(common?.classList.contains("park-sheet"), "the chip sits in the title header").toBe(
      false,
    );
  });

  it("WEB_11_connectors_honesty_connected_status_appears_only_for_fixture_connected_tools", async () => {
    const { root } = await open();
    const synced = connectedTiles(root).filter((t) => /Synced /.test(textOf(t)));
    expect(synced).toHaveLength(connectors.filter((c) => c.st === "connected").length);
    const addRegion = textOf(labelled(root, "Available") as HTMLElement);
    expect(addRegion).not.toMatch(/Synced|Connected just now|Healthy/);
  });

  it("WEB_11_connectors_honesty_no_navigation_or_approval_on_render", async () => {
    const { app } = await open();
    expect(app.go).not.toHaveBeenCalled();
    expect(app.decide).not.toHaveBeenCalled();
    expect(app.addWorld).not.toHaveBeenCalled();
  });
});
