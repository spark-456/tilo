// LIVE8-WEB-1 (FR-SPD-01): Home's spend panel shows the ledger's real spent figure (cents kept, as the KPI tile and the
// Ledger page do), and with no budget set it says so instead of "of $0" and "Forecast $0".
import { describe, expect, it } from "vitest";
import { ledger } from "../../api/fixtures";
import type { Ledger } from "../../api/types";
import { spendOf } from "./homeData";

const live: Ledger = {
  ...ledger,
  currency: "USD",
  budget: 0,
  forecast: 0,
  spent: 0.34,
  tx: [],
  daily: [],
};

describe("FR_SPD_01 LIVE8 Home spend with no budget", () => {
  it("FR_SPD_01 shows the real spent figure once, with a No budget set hint, never $0 of $0", () => {
    const s = spendOf(live);
    expect(s.spent).toBe("$0.34");
    expect(s.of).toBe("No budget set");
    expect(`${s.spent} ${s.of} ${s.forecast}`).not.toMatch(/\$0 of|Forecast \$0/);
  });

  it("FR_SPD_01 keeps the budget and forecast lines when a budget is set", () => {
    const s = spendOf({ ...live, budget: 100, forecast: 40, spent: 12.5 });
    expect(s.spent).toBe("$12.50");
    expect(s.of).toBe("of $100");
    expect(s.forecast).toContain("Forecast $40");
  });
});
