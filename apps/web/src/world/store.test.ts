/**
 * P0-08b-player: FR-WLD-04 unit tests for apps/web/src/world/store.ts (PRD 9.6 "Replay: scrub
 * any finished run; the reducer is deterministic and snapshots every 250 events").
 *
 * Interface under test (module does not exist yet):
 *
 *   export const SNAPSHOT_EVERY = 250;
 *   export interface WorldStore {
 *     apply(event: Event): void;         // append one event, seq must be store.currentSeq()+1
 *     stateAt(seq: number): WorldState;  // reducer.ts's WorldState, restored from the nearest
 *                                         // snapshot at or before `seq`, replaying the rest
 *     snapshotSeqs(): number[];          // seqs a snapshot exists at, ascending
 *     currentSeq(): number;
 *   }
 *   export function createWorldStore(layout: Layout): WorldStore;
 *
 * A synthetic 1,000-event stream (all `agent.working`, cycling over the village-basic layout's
 * five agents/buildings — the exact content does not matter, only that seq is strictly
 * increasing and every event is valid input to reducer.ts) stands in for "a 1,000-event stream"
 * (the acceptance criterion's own number).
 */
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicLayout } from "../../test-support/worldFixtures";
import { reduce } from "./reducer";
import { SNAPSHOT_EVERY, createWorldStore } from "./store";

const layout = villageBasicLayout() as unknown as Layout;
const AGENT_IDS = ["A_dir", "A_l1", "A_s1", "A_s2", "A_v1"];
const BUILDING_IDS = ["B1", "B2", "B3", "B4", "B5"];
const STREAM_LENGTH = 1000;

function makeEvent(i: number): Event {
  const seq = i + 1;
  return {
    v: "1.0",
    id: `01JB5VQ0000000000${String(seq).padStart(9, "0")}`,
    seq,
    ts: new Date(Date.UTC(2026, 8, 29, 9, 30, 0) + i * 1000).toISOString(),
    world_id: "w_village_basic",
    run_id: "r_village_basic_1",
    type: "agent.working",
    actor: AGENT_IDS[i % AGENT_IDS.length],
    target: BUILDING_IDS[i % BUILDING_IDS.length],
    level: "L1",
    district: "D1",
    item: null,
    severity: "info",
    credits: 0,
    summary: `working step ${seq}`,
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

const THOUSAND_EVENTS: Event[] = Array.from({ length: STREAM_LENGTH }, (_, i) => makeEvent(i));

test("FR-WLD-04 store: SNAPSHOT_EVERY is 250 (PRD 9.6)", () => {
  expect(SNAPSHOT_EVERY).toBe(250);
});

test("FR-WLD-04 store: snapshots exist at every 250th seq of a 1,000-event stream", () => {
  const store = createWorldStore(layout);
  for (const event of THOUSAND_EVENTS) store.apply(event);
  expect(store.snapshotSeqs()).toEqual([250, 500, 750, 1000]);
});

test("FR-WLD-04 store: stateAt(seq) equals a from-scratch replay, for every seq of a 1,000-event stream", () => {
  const store = createWorldStore(layout);
  for (const event of THOUSAND_EVENTS) store.apply(event);

  for (let seq = 1; seq <= STREAM_LENGTH; seq++) {
    const expected = reduce(layout, THOUSAND_EVENTS.slice(0, seq));
    expect(store.stateAt(seq), `stateAt(${seq}) diverged from a from-scratch replay`).toEqual(
      expected,
    );
  }
});

test("FR-WLD-04 store: stateAt(0) is the same as reducer.ts's createInitialState (before any event)", () => {
  const store = createWorldStore(layout);
  for (const event of THOUSAND_EVENTS) store.apply(event);
  expect(store.stateAt(0)).toEqual(reduce(layout, []));
});

test("FR-WLD-04 store: snapshots are immutable — later apply() calls never change a snapshot already taken", () => {
  const store = createWorldStore(layout);
  for (const event of THOUSAND_EVENTS.slice(0, 250)) store.apply(event);
  const snapshotAt250 = store.stateAt(250);

  for (const event of THOUSAND_EVENTS.slice(250)) store.apply(event);

  expect(
    store.stateAt(250),
    "stateAt(250) changed after more events were applied past it — the snapshot was mutated",
  ).toEqual(snapshotAt250);
});
