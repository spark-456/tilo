// @vitest-environment happy-dom
// FR-SPD-01 on the Home page (docs/prd-supplement-design-2026-10-06.md section 1.3, row FR-SPD-01 "Ledger, Home"):
// "Five KPI tiles. Done when: every figure equals the credit ledger; 'waiting on you' opens the world."
//
// Today Home draws only the "September spend" strip of the Today panel (spent, budget, forecast, waiting in one
// sentence); it has none of the five tiles (Spent so far, Month-end forecast, Waiting on you, Saved by memory,
// Hours handed back). So every test here that looks for the tiles is RED until a builder adds them; the one
// test that pins the existing strip is GREEN and must stay green (Home.decide.test.tsx pins it too).
// The figures are stated as a function of the SAME ledger object Home was given (see test-support/park/spdKpis.ts).
// Ambiguities resolved (supplement defaults): labels are the five names of FR-SPD-01, case-sensitive; Home is
// mounted at 1440 px, where the Today panel shows; a tile may live in any panel of the page.
import { afterEach, describe, expect, it } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  clickEl,
  lastGo,
  mountHome,
  pageText,
  spiedApi,
} from "../../../../test-support/park/homeHarness";
import {
  KPI_LABELS,
  type KpiLabel,
  controlOf,
  dollars,
  figuresOf,
  pounds,
  tileCandidates,
  tileLabelsPresent,
  tileShowing,
  variedLedger,
} from "../../../../test-support/park/spdKpis";
import { decisions as fixtureDecisions, ledger as fixtureLedger } from "../../api/fixtures";
import type { Decision, Ledger, World } from "../../api/types";

afterEach(cleanup);

/** The fixture Api with the ledger (and optionally the decisions and worlds) replaced by the objects given. */
function apiServing(parts: {
  ledger?: Ledger;
  decisions?: Decision[];
  mapWorlds?: (w: World[]) => World[];
}) {
  const api = spiedApi();
  const { ledger, decisions, mapWorlds } = parts;
  if (ledger) api.getLedger.mockImplementation(async () => ({ data: ledger, source: "fixture" }));
  if (decisions)
    api.getDecisions = (async () => ({
      data: decisions,
      source: "fixture",
    })) as typeof api.getDecisions;
  if (mapWorlds) {
    const base = api.getWorlds.getMockImplementation() ?? api.getWorlds;
    api.getWorlds.mockImplementation(async (...args: unknown[]) => {
      const r = await (base as (...a: unknown[]) => Promise<{ data: World[]; source: "fixture" }>)(
        ...args,
      );
      return { ...r, data: mapWorlds(r.data) };
    });
  }
  return api;
}

function expectTile(root: HTMLElement, label: KpiLabel, figure: string) {
  const tile = tileShowing(root, label, figure);
  const saw = tileCandidates(root, label).map((t) => t.textContent);
  expect(
    tile,
    `Home "${label}" should show ${figure}; tiles named so say ${JSON.stringify(saw)}`,
  ).toBeDefined();
  return tile as HTMLElement;
}

describe("FR_SPD_01_home_five_kpi_tiles: every figure equals the credit ledger", () => {
  // GREEN: pins the existing strip, which the five tiles must not break.
  it("FR_SPD_01_home_keeps_the_september_spend_strip_equal_to_the_ledger", async () => {
    const { el } = await mountHome({ api: apiServing({ ledger: fixtureLedger }) });
    const text = pageText(el);
    expect(text).toContain("September spend");
    expect(text).toContain(pounds(fixtureLedger.spent));
    expect(text).toContain(`Forecast ${pounds(fixtureLedger.forecast)}`);
  });

  // RED today: Home has none of the five tiles.
  it("FR_SPD_01_home_shows_the_five_tiles_each_equal_to_the_fixture_ledger", async () => {
    const { el } = await mountHome({ api: apiServing({ ledger: fixtureLedger }) });
    expect(tileLabelsPresent(el)).toEqual([...KPI_LABELS]);
    const want = figuresOf(fixtureLedger);
    for (const label of KPI_LABELS) expectTile(el, label, want[label]);
  });

  // RED today: and once they exist they must read the ledger Home was given, not carry typed numbers.
  it("FR_SPD_01_home_tiles_follow_a_changed_ledger_and_keep_none_of_the_old_figures", async () => {
    const changed = variedLedger(fixtureLedger);
    const { el } = await mountHome({ api: apiServing({ ledger: changed }) });
    const want = figuresOf(changed);
    const tiles = new Set<HTMLElement>();
    for (const label of KPI_LABELS) tiles.add(expectTile(el, label, want[label]));
    for (const t of tiles)
      for (const stale of Object.values(figuresOf(fixtureLedger)))
        expect(
          t.textContent,
          `tile "${t.textContent}" keeps the fixture figure ${stale}`,
        ).not.toContain(stale);
  });

  // RED today (BQ-DSN-02): a ledger served in USD shows its own unit on every tile of Home too.
  it("FR_SPD_01_home_tiles_use_the_ledgers_own_unit_never_a_fixed_pound_sign", async () => {
    const live: Ledger = { ...variedLedger(fixtureLedger), currency: "USD" };
    const { el } = await mountHome({ api: apiServing({ ledger: live }) });
    const want = figuresOf(live, dollars);
    const poundTiles = KPI_LABELS.filter((label) =>
      expectTile(el, label, want[label]).textContent?.includes("£"),
    );
    expect(poundTiles, "tiles that print a pound sign for a USD ledger").toEqual([]);
  });

  // RED today: the waiting tile is a control that opens the world the waiting decision is in.
  it("FR_SPD_01_home_waiting_on_you_tile_opens_the_world", async () => {
    const rig = await mountHome({ api: apiServing({ ledger: fixtureLedger }) });
    const tile = expectTile(rig.el, "Waiting on you", pounds(3420));
    const control = controlOf(tile);
    expect(control, "the waiting tile is a control").toBeDefined();
    clickEl(control as HTMLElement);
    expect(lastGo(rig.app)).toEqual(["world", { id: "k1" }]);
  });

  // RED today: the world opened is the one the page's data names, not a typed id.
  it("FR_SPD_01_home_waiting_tile_opens_whichever_world_the_decision_is_in", async () => {
    const moved = fixtureDecisions.map((d) => ({ ...d, world: `${d.world}-b` }));
    const api = apiServing({
      ledger: fixtureLedger,
      decisions: moved,
      mapWorlds: (ws) =>
        ws.map((w) => (w.st === "needs" && !w.isNew ? { ...w, id: `${w.id}-b` } : w)),
    });
    const rig = await mountHome({ api });
    const tile = expectTile(rig.el, "Waiting on you", pounds(3420));
    clickEl(controlOf(tile) as HTMLElement);
    expect(lastGo(rig.app)).toEqual(["world", { id: "k1-b" }]);
  });
});
