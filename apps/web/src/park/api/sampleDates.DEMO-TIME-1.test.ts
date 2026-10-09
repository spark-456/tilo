// DEMO-TIME-1: the sample company's dates follow today. Pure: the day is handed in, no clock is read here.
import { describe, expect, it } from "vitest";
import { createFixtureApi } from "./fixtureApi";
import { agenda, ledger, today } from "./fixtures";
import {
  SAMPLE_DAY,
  civilFromDays,
  dated,
  daysFromCivil,
  daysInMonth,
  shiftText,
  weekdayOf,
  withToday,
} from "./sampleDates";

const FRI_9_OCT = { y: 2026, m: 10, d: 9 };

describe("DEMO-TIME-1 calendar arithmetic", () => {
  it("DEMO-TIME-1 the fixture's day is a Thursday and 9 October 2026 a Friday", () => {
    expect(weekdayOf(daysFromCivil(SAMPLE_DAY))).toBe(4);
    expect(weekdayOf(daysFromCivil(FRI_9_OCT))).toBe(5);
    expect(civilFromDays(daysFromCivil(FRI_9_OCT))).toEqual(FRI_9_OCT);
    expect(daysInMonth(2026, 10)).toBe(31);
    expect(daysInMonth(2028, 2)).toBe(29);
  });
});

describe("DEMO-TIME-1 sentences", () => {
  it.each([
    ["Thursday 24 September", "Friday 9 October"],
    ["Thu 24 Sep", "Fri 9 Oct"],
    ["Today · Thu 24 Sep", "Today · Fri 9 Oct"],
    ["Wed 23 Sep", "Thu 8 Oct"],
    ["Mon 28 Sep", "Tue 13 Oct"],
    ["18 Sep", "3 Oct"],
    ["Thu 1 Oct 08:30", "Fri 16 Oct 08:30"],
    ["September 2026", "October 2026"],
    ["Up £120 on August", "Up £120 on September"],
    ["Thu 16:00", "Thu 16:00"],
  ])("DEMO-TIME-1 %s is %s", (before, after) => {
    expect(shiftText(before, FRI_9_OCT)).toBe(after);
  });

  it("DEMO-TIME-1 on the fixture's own day nothing changes", () => {
    expect(shiftText("Thursday 24 September · Thu 24 Sep", SAMPLE_DAY)).toBe(
      "Thursday 24 September · Thu 24 Sep",
    );
  });

  it("DEMO-TIME-1 the sample day crosses a year end", () => {
    expect(shiftText("Thu 24 Sep", { y: 2027, m: 1, d: 2 })).toBe("Sat 2 Jan");
  });
});

describe("DEMO-TIME-1 the Agenda follows the week of today", () => {
  const a = dated(agenda, FRI_9_OCT);
  it("DEMO-TIME-1 names this week's days and today's column", () => {
    expect(a.days).toEqual(["Mon 5", "Tue 6", "Wed 7", "Thu 8", "Fri 9"]);
    expect(a.wkend).toEqual(["Sat 10", "Sun 11"]);
    expect(a.today).toBe(4);
  });
  it("DEMO-TIME-1 earlier days and today's earlier events are past, later ones are not", () => {
    for (const e of a.events) {
      const past = e.d < 4 || (e.d === 4 && e.e <= agenda.now);
      expect(Boolean(e.past), `${e.id}`).toBe(past);
    }
  });
  it("DEMO-TIME-1 a weekend shows Friday as the day of the week it is in", () => {
    expect(dated(agenda, { y: 2026, m: 10, d: 10 }).today).toBe(4);
  });
  it("DEMO-TIME-1 slot labels carry the weekday of their column", () => {
    const slot = a.slots[0];
    expect(slot?.l).toMatch(new RegExp(`^${["Mon", "Tue", "Wed", "Thu", "Fri"][slot?.d ?? 0]} `));
  });
});

describe("DEMO-TIME-1 the Ledger follows the month of today", () => {
  const L = dated(ledger, FRI_9_OCT);
  it("DEMO-TIME-1 holds the days that have passed, with the same total", () => {
    expect(L.daily).toHaveLength(9);
    const sum = (v: number[]) => v.reduce((s, x) => s + x, 0);
    expect(sum(L.daily)).toBeCloseTo(sum(ledger.daily), 6);
    expect(L.period).toMatchObject({
      month: "October",
      short: "Oct",
      year: 2026,
      days: 31,
      day: 9,
      firstWeekday: 4,
    });
    expect(L.period?.today).toBe("Fri 9 Oct");
  });
  it("DEMO-TIME-1 the memory weeks are the four weeks that end today", () => {
    expect(L.memoryWeeks).toEqual(["12–18 Sep", "19–25 Sep", "26 Sep–2 Oct", "3–9 Oct"]);
  });
  it("DEMO-TIME-1 a spike stays inside the days held and never exceeds its day", () => {
    if (L.spike) {
      expect(L.spike.day).toBeLessThanOrEqual(L.daily.length);
      expect(L.spike.amount).toBeLessThanOrEqual(L.daily[L.spike.day - 1] ?? 0);
    }
  });
  it("DEMO-TIME-1 the feed's day labels follow", () => {
    expect(L.activity.some((e) => e.day === "Today · Fri 9 Oct")).toBe(true);
    expect(JSON.stringify(L)).not.toContain("24 Sep");
  });
});

describe("DEMO-TIME-1 the Api", () => {
  it("DEMO-TIME-1 getToday says today, as sample data", async () => {
    const api = withToday(createFixtureApi(), () => FRI_9_OCT);
    const r = await api.getToday();
    expect(r.source).toBe("fixture");
    expect(r.data.long).toBe("Friday 9 October");
    expect(r.data.short).toBe("Fri 9 Oct");
    expect(r.data.time).toBe(today.time);
  });
  it("DEMO-TIME-1 a live answer is left alone", async () => {
    const live = {
      ...createFixtureApi(),
      getToday: async () => ({
        data: { long: "Thursday 24 September", short: "x", time: "y" },
        source: "live" as const,
      }),
    };
    expect((await withToday(live, () => FRI_9_OCT).getToday()).data.long).toBe(
      "Thursday 24 September",
    );
  });
  it("DEMO-TIME-1 the fixture Api alone is untouched", async () => {
    expect((await createFixtureApi().getToday()).data.long).toBe("Thursday 24 September");
  });
});

describe("DEMO-TIME-1 Home's spend panel names the month", () => {
  it("DEMO-TIME-1 the title follows the ledger's month and is September without one", async () => {
    const { spendOf } = await import("../pages/Home/homeData");
    expect(spendOf(dated(ledger, FRI_9_OCT)).month).toBe("October");
    expect(spendOf(ledger).month).toBe("September");
  });
});
