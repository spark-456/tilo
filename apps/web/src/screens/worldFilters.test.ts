import { describe, expect, it } from "vitest";
import { type WorldRow, countsOf, visible } from "./worldFilters";

const row = (
  title: string,
  phase: WorldRow["phase"],
  waiting = 0,
  size: string | null = null,
): WorldRow => ({ title, phase, waiting, size });
const worlds = [
  row("Triage my inbox", "running", 1),
  row("Plan the offsite", "finished"),
  row("Weekly report", "recorded"),
  row("Reconcile invoices", "failed"),
];

describe("S-14 filters (HR-1: counts come from the worlds, never invented)", () => {
  it("counts each status over the worlds the search lets through", () => {
    expect(countsOf(worlds, "")).toEqual({
      all: 4,
      needs: 1,
      running: 1,
      scheduled: 0,
      finished: 1,
    });
    expect(countsOf(worlds, "  PLAN ")).toEqual({
      all: 1,
      needs: 0,
      running: 0,
      scheduled: 0,
      finished: 1,
    });
  });

  it("lists a world once its status matches and its title contains the search", () => {
    expect(visible(worlds, "all", "").map((w) => w.title)).toHaveLength(4);
    expect(visible(worlds, "needs", "").map((w) => w.title)).toEqual(["Triage my inbox"]);
    expect(visible(worlds, "finished", "report")).toEqual([]);
    expect(visible(worlds, "all", "report").map((w) => w.title)).toEqual(["Weekly report"]);
  });

  it("filters by the layout's size; a world whose layout has not loaded is only in All sizes", () => {
    const sized = [
      row("A", "running", 0, "village"),
      row("B", "finished", 0, "city"),
      row("C", "recorded"),
    ];
    expect(visible(sized, "all", "", "village").map((w) => w.title)).toEqual(["A"]);
    expect(visible(sized, "all", "", "all")).toHaveLength(3);
    expect(visible(sized, "all", "", "town")).toEqual([]);
    expect(countsOf(sized, "", "city")).toMatchObject({ all: 1, finished: 1, running: 0 });
  });

  it("never lists a world as scheduled: this build has no schedule data", () => {
    expect(visible(worlds, "scheduled", "")).toEqual([]);
  });
});
