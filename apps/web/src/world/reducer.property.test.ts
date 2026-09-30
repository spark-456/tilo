/**
 * P0-08b-player: FR-WLD-04 property test ("Same layout and events give deep-equal state ... in
 * two separate instances (fast-check property)").
 *
 * Same interface as reducer.test.ts (reduce, applyEvent, createInitialState, WorldState); see
 * that file's header for the full contract. This file generates random-length streams of a
 * single known, harmless event type (`agent.working`, side_effect: false, no gate) over the
 * village-basic layout's real agent/building ids, and checks that `reduce` is a deterministic,
 * pure function of (layout, events): the same input always produces a deep-equal output,
 * whether called twice ("two separate instances") or built by folding `applyEvent` one event at
 * a time ("from scratch").
 */
import type { Event, Layout } from "@tilo/contracts";
import fc from "fast-check";
import { expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { applyEvent, createInitialState, reduce } from "./reducer";

const layout = villageBasicLayout() as unknown as Layout;
const AGENT_IDS = ["A_dir", "A_l1", "A_s1", "A_s2", "A_v1"];
const BUILDING_IDS = ["B1", "B2", "B3", "B4", "B5"];

function toEvent(
  i: number,
  actor: string,
  target: string,
  credits: number,
  summary: string,
): Event {
  return {
    v: "1.0",
    id: `01JB5VQ00000000000000${String(i + 1).padStart(5, "0")}`,
    seq: i + 1,
    ts: new Date(Date.UTC(2026, 8, 29, 9, 30, 0) + i * 1000).toISOString(),
    world_id: "w_village_basic",
    run_id: "r_village_basic_1",
    type: "agent.working",
    actor,
    target,
    level: "L1",
    district: "D1",
    item: null,
    severity: "info",
    credits,
    summary: summary.length > 0 ? summary.slice(0, 140) : "working",
    cause: null,
    vis: "all",
    authz: null,
    data: { unit: null },
    trace: {
      model_role: null,
      profile: null,
      tokens_in: null,
      tokens_out: null,
      tool: null,
      latency_ms: null,
      archive_ref: null,
    },
  } as unknown as Event;
}

const eventStreamArb = fc
  .array(
    fc.record({
      actor: fc.constantFrom(...AGENT_IDS),
      target: fc.constantFrom(...BUILDING_IDS),
      credits: fc.float({ min: 0, max: 5, noNaN: true }),
      summary: fc.string({ minLength: 0, maxLength: 30 }),
    }),
    { minLength: 0, maxLength: 30 },
  )
  .map((rows) => rows.map((r, i) => toEvent(i, r.actor, r.target, r.credits, r.summary)));

test("FR-WLD-04 property: reduce(layout, events) is deterministic across two separate calls", () => {
  fc.assert(
    fc.property(eventStreamArb, (events) => {
      const a = reduce(layout, events);
      const b = reduce(layout, events);
      expect(a).toEqual(b);
    }),
    { numRuns: 50 },
  );
});

test("FR-WLD-04 property: reduce(layout, events) equals folding applyEvent one event at a time (from scratch)", () => {
  fc.assert(
    fc.property(eventStreamArb, (events) => {
      let folded = createInitialState(layout);
      for (const event of events) folded = applyEvent(folded, event, layout);
      expect(reduce(layout, events)).toEqual(folded);
    }),
    { numRuns: 50 },
  );
});
