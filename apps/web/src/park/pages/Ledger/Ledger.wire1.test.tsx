// @vitest-environment happy-dom
// WIRE-1 (Park wiring, first slice; PRD 9.4 HR-1..HR-7): the Ledger page renders a LIVE Ledger as the
// /costs mapper produces it: budget 0, forecast 0, empty daily/tx/runs/memory/hours/activity, and a few real
// `by` rows. It must not crash, must not print NaN or Infinity (text or SVG attributes), must say it is live
// (`data-source="live"`), and must not show any prototype figure or name. Mounted the way Ledger.page.test.tsx
// does: the real ParkProvider and AppCtx, with an Api whose getLedger returns the live shape.
// Pinned for the builder: no copy is pinned for the empty state (the design has none); the page may show a
// quiet "no data yet" line or dashes, but a zero budget never becomes a percentage, a "£NaN" or an SVG
// path with NaN. Ambiguity (BQ-WIRE1-1): amounts are US dollars as served; the page may keep formatting
// pounds until the currency is decided, so no currency symbol is asserted.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler } from "../../../../test-support/park/appHarness";
import { cleanup, mount, q } from "../../../../test-support/park/componentsHarness";
import { ledger as fixtureLedger } from "../../api/fixtures";
import { NotBuilt } from "../../api/liveApi";
import type { Ledger } from "../../api/types";
import { ParkProvider, useApp } from "../../app/context";
import { LedgerPage } from "./LedgerPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.pushState({}, "", "/");
});

/** What `ledgerFromCosts` returns for a small report (WIRE-1): served fields only, the rest empty. */
const live = (over: Partial<Ledger> = {}): Ledger => ({
  budget: 0,
  spent: 1.21,
  forecast: 0,
  daily: [],
  by: {
    world: { head: "", rows: [] },
    tool: {
      head: "",
      rows: [
        ["fast", 0.5],
        ["deep", 0.71],
      ],
    },
    role: {
      head: "",
      rows: [
        ["research", 0.9],
        ["Unlabelled", 0.31],
      ],
    },
  },
  tx: [],
  runs: [],
  waits: { buckets: [], types: [] },
  memory: [],
  hours: [],
  activity: [],
  ...over,
});

const settle = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

function Shell() {
  const app = useApp();
  return (
    <div data-park="" data-time={app.time}>
      <LedgerPage app={app} />
    </div>
  );
}

async function renderLive(ledger: Ledger, vw = 1440) {
  window.history.pushState({}, "", "/park/ledger");
  const api = fakeApi();
  // A live Api that has only /costs: getLedger answers, getDecisions is not built.
  api.getLedger = (() => Promise.resolve({ data: ledger, source: "live" })) as typeof api.getLedger;
  api.getDecisions = (() =>
    Promise.reject(new NotBuilt("getDecisions"))) as typeof api.getDecisions;
  const m = mount(
    <ParkProvider
      api={api}
      navigate={vi.fn()}
      schedule={fakeScheduler().schedule}
      viewport={{ vw, vh: 900 }}
    >
      <Shell />
    </ParkProvider>,
  );
  await settle();
  return m;
}

const BAD = /NaN|Infinity|undefined|\[object/;

describe("WIRE_1_ledger_page: a live Ledger with zero budget and empty arrays", () => {
  it("WIRE_1_ledger_live_zero_budget_renders_no_NaN_or_Infinity_anywhere", async () => {
    const err = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const { container } = await renderLive(live());
    expect(q(container, "[data-park-ledger]").getAttribute("data-source")).toBe("live");
    expect(q(container, "h1").textContent).toBe("Ledger");
    expect(container.textContent ?? "").not.toMatch(BAD);
    expect(container.innerHTML, "SVG paths, widths and attributes").not.toMatch(BAD);
    expect(err, "no console error while rendering").not.toHaveBeenCalled();
  });

  it("WIRE_1_ledger_live_zero_budget_never_prints_a_percentage_of_the_budget", async () => {
    const { container } = await renderLive(live());
    // spent / 0 is not a share of anything: no "<n>% of" line, however it is worded.
    expect(container.textContent ?? "").not.toMatch(/\d\s*%\s*of\b/);
    expect(container.textContent ?? "").not.toMatch(/-\s*\d[\d,.]*\s*under budget/);
  });

  it("WIRE_1_ledger_live_shows_only_live_numbers_no_prototype_figure_or_name", async () => {
    const { container } = await renderLive(live());
    const text = container.textContent ?? "";
    for (const [name] of [
      ...fixtureLedger.by.world.rows,
      ...fixtureLedger.by.tool.rows,
      ...fixtureLedger.by.role.rows,
    ]) {
      expect(text, `prototype row "${name}"`).not.toContain(name);
    }
    expect(text).not.toContain("Laptop Depot");
    expect(text).not.toContain("K1 electric scooter");
    expect(text).not.toContain("£2,412");
    expect(text).not.toContain("£8,000");
    expect(text).not.toContain("£6,300");
  });

  it("WIRE_1_ledger_live_all_empty_arrays_and_no_by_rows_still_renders", async () => {
    const empty = live({
      spent: 0,
      by: {
        world: { head: "", rows: [] },
        tool: { head: "", rows: [] },
        role: { head: "", rows: [] },
      },
    });
    const { container } = await renderLive(empty);
    expect(q(container, "[data-park-ledger]").getAttribute("data-source")).toBe("live");
    expect(container.textContent ?? "").not.toMatch(BAD);
    expect(container.innerHTML).not.toMatch(BAD);
  });

  it("WIRE_1_ledger_live_zero_budget_also_holds_on_a_phone_width", async () => {
    const { container } = await renderLive(live(), 390);
    expect(container.textContent ?? "").not.toMatch(BAD);
    expect(container.innerHTML).not.toMatch(BAD);
  });
});

describe("WIRE_1_ledger_page: live amounts in the currency served", () => {
  it("WIRE_1_ledger_live_usd_amounts_show_dollars_and_never_pounds", async () => {
    const { container } = await renderLive(live({ currency: "USD" }));
    const text = container.textContent ?? "";
    expect(text, "spent so far").toContain("$1.21");
    expect(text, "a where-it-goes row").toContain("$0.71");
    expect(text).not.toContain("£");
  });

  it("WIRE_1_ledger_without_a_currency_keeps_pounds_as_the_fixture_does", async () => {
    const { container } = await renderLive(live());
    expect(container.textContent ?? "").toContain("£1.21");
  });
});
