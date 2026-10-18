import type { Event, Layout } from "@tilo/contracts";
import { describe, expect, it } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf, standAt, standSlotOffset, standZone } from "./frame";
import { reduce } from "./reducer";

describe("TW-2 standing slots specification", () => {
  it("computes slot offsets exactly 0.75 cells apart", () => {
    // Slot 0: center (0)
    expect(standSlotOffset(0)).toBe(0);
    // Slot 1: left (-0.75)
    expect(standSlotOffset(1)).toBe(-0.75);
    // Slot 2: right (+0.75)
    expect(standSlotOffset(2)).toBe(0.75);
    // Slot 3: left row continuation (-1.5)
    expect(standSlotOffset(3)).toBe(-1.5);
    // Slot 4: right row continuation (+1.5)
    expect(standSlotOffset(4)).toBe(1.5);

    // Adjacent slot spacing check
    expect(Math.abs(standSlotOffset(1) - standSlotOffset(0))).toBe(0.75);
    expect(Math.abs(standSlotOffset(2) - standSlotOffset(0))).toBe(0.75);
    expect(Math.abs(standSlotOffset(3) - standSlotOffset(1))).toBe(0.75);
    expect(Math.abs(standSlotOffset(4) - standSlotOffset(2))).toBe(0.75);
  });

  it("standZone covers all 3 standing slots in front of a building", () => {
    const rect = { x: 10, y: 10, w: 4, d: 4 };
    const zone = standZone(rect, 0);
    expect(zone.x1).toBeGreaterThan(zone.x0);
    expect(zone.y1).toBeGreaterThanOrEqual(zone.y0);

    // Slot 0, 1, 2 must all fall within standZone
    for (const slot of [0, 1, 2]) {
      const pos = standAt(rect, "building", 0, slot);
      expect(pos.cx).toBeGreaterThanOrEqual(zone.x0);
      expect(pos.cx).toBeLessThanOrEqual(zone.x1);
      expect(pos.cy).toBeGreaterThanOrEqual(zone.y0);
      expect(pos.cy).toBeLessThanOrEqual(zone.y1);
    }
  });

  it("agents sharing a building stand in distinct slots and never pile up", () => {
    const layout = villageBasicLayout() as unknown as Layout;
    const events: Event[] = [
      {
        v: "1.0",
        id: "ev1",
        seq: 1,
        ts: "2026-10-16T09:00:00.000Z",
        world_id: "w",
        run_id: "r",
        type: "agent.spawned",
        actor: "system",
        target: "A_dir",
        level: "L1",
        district: "D1",
        item: null,
        severity: "info",
        credits: 0,
        summary: "spawned",
        cause: null,
        vis: "all",
        authz: null,
        data: { role: "director" },
        trace: {},
      } as unknown as Event,
      {
        v: "1.0",
        id: "ev2",
        seq: 2,
        ts: "2026-10-16T09:00:01.000Z",
        world_id: "w",
        run_id: "r",
        type: "agent.spawned",
        actor: "A_dir",
        target: "A_l1",
        level: "L1",
        district: "D1",
        item: null,
        severity: "info",
        credits: 0,
        summary: "spawned",
        cause: null,
        vis: "all",
        authz: null,
        data: { role: "lead" },
        trace: {},
      } as unknown as Event,
      {
        v: "1.0",
        id: "ev3",
        seq: 3,
        ts: "2026-10-16T09:00:02.000Z",
        world_id: "w",
        run_id: "r",
        type: "agent.moved",
        actor: "A_dir",
        target: "B1",
        level: "L1",
        district: "D1",
        item: null,
        severity: "info",
        credits: 0,
        summary: "moved",
        cause: null,
        vis: "all",
        authz: null,
        data: { from: "B1" },
        trace: {},
      } as unknown as Event,
      {
        v: "1.0",
        id: "ev4",
        seq: 4,
        ts: "2026-10-16T09:00:03.000Z",
        world_id: "w",
        run_id: "r",
        type: "agent.moved",
        actor: "A_l1",
        target: "B1",
        level: "L1",
        district: "D1",
        item: null,
        severity: "info",
        credits: 0,
        summary: "moved",
        cause: null,
        vis: "all",
        authz: null,
        data: { from: "B1" },
        trace: {},
      } as unknown as Event,
    ];

    const state = reduce(layout, events);
    const frame = frameOf(layout, state);
    const dir = frame.agents.find((a) => a.id === "A_dir");
    const lead = frame.agents.find((a) => a.id === "A_l1");

    expect(dir).toBeDefined();
    expect(lead).toBeDefined();
    // They share building B1, so their foot positions must be distinct
    const dist = Math.hypot((dir?.cx ?? 0) - (lead?.cx ?? 0), (dir?.cy ?? 0) - (lead?.cy ?? 0));
    expect(dist).toBeGreaterThan(14);
  });
});
