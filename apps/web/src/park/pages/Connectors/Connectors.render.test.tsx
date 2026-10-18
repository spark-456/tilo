// @vitest-environment happy-dom
// WEB-11 render, copy and search (plan section 10; README "Connectors"; inventory.md "Tilo App
// Connectors.dc.html"; design reference `Tilo App Connectors.dc.html`). Data comes only through the Park
// Api, here the fixture Api, so every tile is checked against the typed fixtures, not retyped by hand.
//
// Defaults taken where the sources are silent (listed in the WEB-11 report):
// - The Api has no connector write (README lists "connector reconnect/sync" as a server call to add), so
//   connect, reconnect, level and disconnect are page-local state, as in the design (`st`, `lvl`).
// - The "Sample data" chip belongs to the shell (one chip in the WEB-3b top nav, AG-WEB ruling): the page
//   renders no chip and no "Sample data recorded for the demo..." line, and that absence is pinned.
// - The page takes only `{ app }` and reads through useParkApi() inside <ParkProvider> (WEB-3a).
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
  makeApp,
  renderPage,
  spyApi,
  textOf,
  tileFor,
  typeInto,
  waitFor,
} from "../../../../test-support/park/connectorsDom";
import { connectors } from "../../api/fixtures";
import { colorLogoOf } from "./BrandIcon";

afterEach(cleanup);

const LV = ["", "Read", "Draft", "Act"];
const GOOGLE_IDS = new Set(["gmail", "gcal", "google_calendar", "gdrive", "google_drive"]);
const isGoogle = (id: string) => GOOGLE_IDS.has(id.toLowerCase());
const on = connectors.filter(
  (c) => isGoogle(c.id) && (c.st === "connected" || c.st === "attention"),
);
const comingLater = connectors.filter(
  (c) => !isGoogle(c.id) && c.id.toLowerCase() !== "canva" && c.name.toLowerCase() !== "canva",
);

async function open() {
  const app = makeApp();
  const api = spyApi();
  const m = await renderPage(app, api);
  await waitFor(() => connectedTiles(m.container).length > 0, "the Connected tiles");
  return { app, api, m, root: m.container };
}

describe("WEB_11_connectors_render: every designed element", () => {
  it("WEB_11_connectors_render_heading_subtitle_search_and_both_regions", async () => {
    const { root } = await open();
    const h1 = root.querySelector("h1");
    expect(h1 && textOf(h1)).toBe("Connectors");
    expect(root.querySelectorAll("h1")).toHaveLength(1);
    const search = labelled(root, "Search connectors");
    expect(search?.tagName).toBe("INPUT");
    expect(search?.getAttribute("placeholder")).toBe("Find an app");
    expect(labelled(root, "Connected")).not.toBeNull();
    expect(labelled(root, "Coming later")).not.toBeNull();
    // PageSheet with the design's 22px gap: the default of .park-sheet or an explicit gap of 22.
    const sheets = root.querySelectorAll<HTMLElement>(".park-sheet");
    expect(sheets).toHaveLength(1);
    expect(["", "22px"]).toContain(sheets[0]?.style.gap ?? "");
  });

  it("WEB_11_connectors_render_one_tile_per_connected_fixture_in_fixture_order", async () => {
    const { root } = await open();
    const tiles = connectedTiles(root);
    expect(on).toHaveLength(3);
    expect(tiles).toHaveLength(6);
    for (const c of on) {
      const tile = tileFor(root, c.name);
      expect(tile, `${c.name} tile`).toBeDefined();
      const t = textOf(tile as HTMLElement);
      const level = LV[c.level ?? 1] as string;
      const sync = c.st === "attention" ? c.sync : "Connected";
      if (!colorLogoOf(c.id)) expect(t.startsWith(c.mono), `${c.name} monogram`).toBe(true);
      expect(t, `${c.name} name`).toContain(c.name);
      expect(t, `${c.name} account`).toContain(c.acct ?? "");
      expect(t, `${c.name} level chip`).toContain(level);
      expect(t, `${c.name} sync line`).toContain(sync as string);
      expect(t, `${c.name} used by`).toContain(`Used by ${c.used?.length ?? 0}`);
    }
  });

  it("WEB_11_connectors_render_literal_spot_checks_of_the_first_and_the_attention_tile", async () => {
    const { root } = await open();
    const gmail = textOf(tileFor(root, "Gmail") as HTMLElement);
    for (const s of ["alex@northwind.co", "Act", "Connected", "Manage", "Used by 3"]) {
      expect(gmail).toContain(s);
    }
    const cal = textOf(tileFor(root, "Google Calendar") as HTMLElement);
    expect(cal).toContain("Connected");
    expect(cal).not.toContain("Example only");
    expect(cal).not.toMatch(/synced (live|\d)/i);
    const drive = textOf(tileFor(root, "Google Drive") as HTMLElement);
    expect(drive).toContain("Northwind shared drive");
    expect(drive).toContain("Read");
    expect(drive).toContain("Connected");
  });

  it("WEB_11_connectors_render_coming_later_row_has_items_and_never_canva", async () => {
    const { root } = await open();
    const region = labelled(root, "Coming later") as HTMLElement;
    expect(region).not.toBeNull();
    const text = textOf(region);
    expect(text.toLowerCase()).not.toContain("canva");
    expect(comingLater.length).toBeGreaterThan(0);
    for (const c of comingLater) {
      expect(text, c.name).toContain(c.name);
    }
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
      "The apps Tilo can use for you. You decide what it may do in each one.",
      "Connected",
      "Coming later",
    ]) {
      expect(hasExactText(root, s), `"${s}"`).toBe(true);
    }
  });

  it("WEB_11_connectors_copy_count_reads_3_connected_beside_the_title_and_the_section", async () => {
    const { root } = await open();
    expect(countExactText(root, "3 connected")).toBe(2);
  });
});

describe("WEB_11_connectors_search: filters both sections by name and category", () => {
  const search = (root: HTMLElement) => labelled(root, "Search connectors") as HTMLInputElement;

  it("WEB_11_connectors_search_by_name_is_case_insensitive_and_updates_the_count", async () => {
    const { root } = await open();
    typeInto(search(root), "DRIVE");
    await flush();
    const cards = on.filter((c) => tileFor(root, c.name));
    expect(cards).toHaveLength(1);
    expect(cards[0]?.name).toBe("Google Drive");
    expect(countExactText(root, "1 connected")).toBe(2);
  });

  it("WEB_11_connectors_search_empty_state_shows_when_no_match", async () => {
    const { root } = await open();
    typeInto(search(root), "xyznomatch");
    await flush();
    expect(countExactText(root, "0 connected")).toBe(1);
    expect(root.querySelector('[data-testid="connectors-empty"]')).not.toBeNull();
    expect(textOf(root)).toContain("No matching connectors");
  });

  it("WEB_11_connectors_search_clearing_restores_all", async () => {
    const { root } = await open();
    typeInto(search(root), "drive");
    await flush();
    expect(countExactText(root, "1 connected")).toBe(2);
    typeInto(search(root), "");
    await flush();
    expect(countExactText(root, "3 connected")).toBe(2);
  });
});

describe("WEB_11_connectors_honesty: fixture data is labelled, statuses come from data", () => {
  it("WEB_11_connectors_honesty_the_page_renders_no_sample_data_chip_or_line_the_shell_owns_it", async () => {
    const { root } = await open();
    expect(countExactText(root, "Sample data")).toBe(0);
    expect(textOf(root)).not.toContain("Sample data");
    expect(hasExactText(root, "Sample data recorded for the demo, not your workspace")).toBe(false);
  });

  it("WEB_11_connectors_honesty_data_is_read_through_the_provided_api", async () => {
    const { api } = await open();
    expect(api.getConnectors).toHaveBeenCalled();
  });

  it("WEB_11_connectors_honesty_connected_status_appears_only_for_fixture_connected_tools", async () => {
    const { root } = await open();
    const synced = connectedTiles(root).filter((t) => /Example only|Not synced/.test(textOf(t)));
    expect(synced).toHaveLength(0);
    const strips = root.querySelectorAll(".park-connectors-strip");
    expect(strips).toHaveLength(1);
    expect(textOf(strips[0] as Element)).toContain("Not synced");
  });

  it("WEB_11_connectors_honesty_no_navigation_or_approval_on_render", async () => {
    const { app } = await open();
    expect(app.go).not.toHaveBeenCalled();
    expect(app.decide).not.toHaveBeenCalled();
    expect(app.addWorld).not.toHaveBeenCalled();
  });
});
