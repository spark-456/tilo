// @vitest-environment happy-dom
// WIRE-1 extra (a): the Profile "Agent spend" bar divides spent by budget. A live Ledger has budget 0 (the
// /costs report serves no budget), so the bar must not become NaN% or Infinity%, and spent over budget must not
// push the fill past the track. Pinned: budget <= 0 gives width "0%" (an empty bar, not a guess); otherwise
// the width is round(spent / budget * 100) clamped to 0..100 (30% for the design's 2,412 of 8,000 stays 30%).
// The spend card is on the "Plan and billing" tab: `button.park-profile-spend` holds the `.park-profile-fill`.
import fc from "fast-check";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { ledger as fixtureLedger } from "../../api/fixtures";
import type { Ledger } from "../../api/types";
import { cleanup, openTab, renderProfile, spyApi } from "./testApp";

afterEach(cleanup);

async function spendBar(spent: number, budget: number) {
  const api = spyApi();
  const data: Ledger = { ...fixtureLedger, spent, budget };
  api.getLedger = vi.fn(async () => ({ data, source: "live" as const }));
  const { root } = await renderProfile(makeApp(), api);
  await openTab(root, "Plan and billing");
  const card = root.querySelector<HTMLElement>("button.park-profile-spend");
  const fill = root.querySelector<HTMLElement>(".park-profile-fill");
  if (!card || !fill) throw new Error("no spend card or fill on the Plan and billing tab");
  return { card, fill, width: fill.style.width };
}

const percent = (width: string): number => Number.parseFloat(width);

describe("WIRE_1_profile_spend_bar: a zero budget and an overspend", () => {
  it("WIRE_1_profile_spend_bar_zero_budget_is_an_empty_bar_not_NaN_or_Infinity", async () => {
    for (const spent of [0, 1.21, 5000]) {
      const { card, width } = await spendBar(spent, 0);
      expect(width, `spent ${spent} of 0`).toBe("0%");
      expect(card.outerHTML).not.toMatch(/NaN|Infinity/);
      cleanup();
    }
  });

  it("WIRE_1_profile_spend_bar_over_budget_stops_at_the_track_width_100", async () => {
    const { width } = await spendBar(9000, 8000); // 113% of the budget
    expect(width).toBe("100%");
  });

  it("WIRE_1_profile_spend_bar_in_budget_keeps_the_designed_rounding", async () => {
    expect((await spendBar(2412, 8000)).width).toBe("30%");
    cleanup();
    expect((await spendBar(4000, 8000)).width).toBe("50%");
  });

  it("WIRE_1_profile_spend_bar_property_width_is_always_a_percentage_between_0_and_100", async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.double({ min: 0, max: 1e7, noNaN: true, noDefaultInfinity: true }),
        fc.oneof(
          fc.constant(0),
          fc.double({ min: 0, max: 1e7, noNaN: true, noDefaultInfinity: true }),
        ),
        async (spent, budget) => {
          const { card, width } = await spendBar(spent, budget);
          cleanup();
          expect(width).toMatch(/^\d+(\.\d+)?%$/);
          expect(percent(width)).toBeGreaterThanOrEqual(0);
          expect(percent(width)).toBeLessThanOrEqual(100);
          expect(card.outerHTML).not.toMatch(/NaN|Infinity/);
        },
      ),
      { numRuns: 25 },
    );
  });
});
