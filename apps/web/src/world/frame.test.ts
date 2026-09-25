/**
 * P0-08b-player: FR-WLD-04 unit tests for apps/web/src/world/frame.ts.
 *
 * Interface under test (module does not exist yet):
 *
 *   export function frameOf(layout: Layout, state: WorldState): unknown; // plain-data display list
 *
 * `frameOf` is a pure function of (layout, state) that turns a WorldState (reducer.ts) into the
 * plain-data display list the PixiJS renderer draws (PRD 9.6/9.7: "a pure frame function
 * (layout, state) -> plain-data display list the renderer draws"). "Plain data" means the
 * result survives a JSON round-trip unchanged: no functions, no class instances, no `Map`/`Set`,
 * no `undefined` values, no cycles.
 */
import type { Layout } from "@tilo/contracts";
import { expect, test } from "vitest";
import { villageBasicEvents, villageBasicLayout } from "../../test-support/worldFixtures";
import { frameOf } from "./frame";
import { reduce } from "./reducer";

const layout = villageBasicLayout() as unknown as Layout;
const events = villageBasicEvents();

test("FR-WLD-04 frame: frameOf(layout, state) is plain data (survives a JSON round-trip unchanged)", () => {
  const state = reduce(layout, events as never);
  const frame = frameOf(layout, state);
  const roundTripped = JSON.parse(JSON.stringify(frame));
  expect(roundTripped).toEqual(frame);
});

test("FR-WLD-04 frame: same layout and state give a deep-equal frame across two separate calls", () => {
  const state = reduce(layout, events as never);
  const a = frameOf(layout, state);
  const b = frameOf(layout, state);
  expect(a).toEqual(b);
});

test("FR-WLD-04 frame: frameOf does not mutate the state it is given", () => {
  const state = reduce(layout, events as never);
  Object.freeze(state);
  expect(() => frameOf(layout, state)).not.toThrow();
});

test("FR-WLD-04 frame: replaying to the same seq from two independently-built states gives a deep-equal frame", () => {
  // "from scratch" vs "in two separate instances" at the frame level, mirroring reducer.test.ts.
  const half = events.slice(0, Math.ceil(events.length / 2));
  const stateA = reduce(layout, half as never);
  const stateB = reduce(layout, half as never);
  expect(frameOf(layout, stateA)).toEqual(frameOf(layout, stateB));
});
