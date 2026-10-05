import type { Layout } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { levelRows, scrubMarks } from "./levels";
import { reduce } from "./reducer";

const layout = LAYOUT_VILLAGE_BASIC as unknown as Layout;
const rowsAt = (seq: number, l: Layout = layout) => {
  const events = EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= seq);
  return levelRows(l, reduce(l, events), events);
};

describe("PRD-18.3 S-04 levels panel: every figure is derived from recorded events (HR-1)", () => {
  it("shows no progress and no line before the level has any event", () => {
    const [row] = rowsAt(3);
    expect(row).toMatchObject({ id: "L1", number: 1, name: "Inbox", percent: 0, line: null });
    expect(row?.active).toBe(false);
  });

  it("takes the latest summary of the level and marks it active", () => {
    const events = EVENTS_VILLAGE_BASIC.filter((e) => e.seq <= 30);
    const [row] = rowsAt(30);
    const latest = [...events].reverse().find((e) => e.level === "L1");
    expect(row?.line).toBe(latest?.summary);
    expect(row?.active).toBe(true);
  });

  it("counts finished buildings, and a finished level is 100", () => {
    const partial = rowsAt(39)[0]?.percent ?? -1;
    expect(partial).toBeGreaterThan(0);
    expect(partial).toBeLessThan(100);
    expect(rowsAt(44)[0]?.percent).toBe(100);
  });

  it("lists the highest level first", () => {
    const upper = structuredClone(layout) as Layout;
    const first = upper.semantic.levels[0];
    if (!first) throw new Error("fixture has a level");
    const [district] = first.districts;
    const [building] = district?.buildings ?? [];
    // A second level whose one building no event has touched.
    upper.semantic.levels.push({
      ...first,
      id: "L2",
      name: "Replies",
      districts: [{ ...district, id: "D2", buildings: [{ ...building, id: "B9" }] }],
    } as never);
    const rows = rowsAt(44, upper);
    expect(rows.map((r) => [r.number, r.name, r.percent])).toEqual([
      [2, "Replies", 0],
      [1, "Inbox", 100],
    ]);
  });
});

describe("PRD-18.3 S-04 scrubber marks: one per registered decision, finish or problem event", () => {
  it("marks the decision asked for and the finishes, at the stop after each event", () => {
    expect(scrubMarks(EVENTS_VILLAGE_BASIC)).toEqual([
      { index: 34, kind: "decision" },
      { index: 43, kind: "done" },
      { index: 44, kind: "done" },
    ]);
  });

  it("marks nothing for an unregistered type (HR-5)", () => {
    const odd = { ...EVENTS_VILLAGE_BASIC[0], type: "approval.requested.future" };
    expect(scrubMarks([odd] as never)).toEqual([]);
  });

  it("marks a raised alert and a failed run as problems", () => {
    const at = (type: string) => ({ ...EVENTS_VILLAGE_BASIC[0], type });
    expect(scrubMarks([at("alert.raised"), at("world.failed")] as never)).toEqual([
      { index: 1, kind: "problem" },
      { index: 2, kind: "problem" },
    ]);
  });
});
