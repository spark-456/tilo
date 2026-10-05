// NFR-10 (PRD 17.1): "Scrub to any point in a finished run: <= 500 ms for <= 5,000 events".
// Written from the PRD text, apart from the FR-WLD-08 timing tests: the scrubber's work for one
// stop is the state at that point and the frame the stage draws from it, so both are timed, for
// EVERY point of a 5,000-event run (not a sample), and each one is held to the full 500 ms.
import type { Event, Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import {
  VILLAGE_BASIC_STREAM_PATH,
  readJsonl,
  villageBasicLayout,
} from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { indexToPoint } from "./replay";
import { createWorldStore } from "./store";

const layout = villageBasicLayout() as unknown as Layout;
const village = readJsonl(VILLAGE_BASIC_STREAM_PATH) as unknown as Event[];
const AGENTS = ["A_dir", "A_l1", "A_s1", "A_s2", "A_v1"];
const BUILDINGS = ["B1", "B2", "B3", "B4", "B5"];
const RUN_LENGTH = 5_000;
const BUDGET_MS = 500;

function finishedRun(count: number): Event[] {
  const base = village[0] as Event;
  return Array.from({ length: count }, (_, i) => ({
    ...base,
    id: `01JB5VQ${String(i + 1).padStart(19, "0")}`,
    seq: i + 1,
    ts: new Date(Date.UTC(2026, 8, 29, 9, 30, 0) + i * 1000).toISOString(),
    type: i % 2 === 0 ? "agent.working" : "agent.moved",
    actor: AGENTS[i % AGENTS.length],
    target: BUILDINGS[i % BUILDINGS.length],
  })) as Event[];
}

test("NFR-10 scrub: every point of a 5,000-event finished run is shown within 500 ms", () => {
  const events = finishedRun(RUN_LENGTH);
  const store = createWorldStore(layout);
  for (const event of events) store.apply(event);

  let worst = { ms: 0, point: 0 };
  for (let i = 0; i <= RUN_LENGTH; i++) {
    const point = indexToPoint(events, i);
    const start = performance.now();
    const state = store.stateAt(point);
    frameOf(layout, state);
    const ms = performance.now() - start;
    expect(state.seq, `the state at point ${point}`).toBe(point);
    if (ms > worst.ms) worst = { ms, point };
  }
  expect(worst.ms, `slowest scrub (point ${worst.point})`).toBeLessThanOrEqual(BUDGET_MS);
}, 120_000);
