// @vitest-environment happy-dom
/**
 * TILO-T-WORLD step 6 (design PROMPT section 3, "Playback"): a finished world replays at 2200, 1100 or 260 ms per
 * event; Pause holds; Catch up falls back to 1x at the end. It only moves the replay point (display state, HR-4).
 */
import type { Layout } from "@tilo/contracts";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../test-support/park/componentsHarness";
import { villageBasicLayout } from "../../../test-support/worldFixtures";
import { ev, fakeWorld, resetEvents, withClient } from "../../../test-support/worldLive";
import { getReplayPoint, setReplayPoint } from "../../world/replay";
import { PlaybackBar } from "./PlaybackBar";
import { STEP_MS, afterStep } from "./playback";

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  vi.useRealTimers();
  cleanup();
  setReplayPoint("w_live", null);
});

const layout = villageBasicLayout() as unknown as Layout;
const run = (end = true) => {
  resetEvents();
  return [
    ev("world.started", "s", "w"),
    ev("agent.moved", "A_l1", "B1"),
    ev("agent.moved", "A_s1", "B2"),
    ...(end ? [ev("world.completed", "A_dir", "w")] : []),
  ];
};
const open = async (events = run()) => {
  const m = mount(withClient(fakeWorld(layout, events).client, <PlaybackBar worldId="w_live" />));
  await act(async () => {
    await Promise.resolve();
  });
  return m;
};
const press = (m: { container: HTMLElement }, name: string) =>
  click(
    [...m.container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes(name),
    ) as Element,
  );
const tick = (ms: number) => act(async () => void vi.advanceTimersByTime(ms));

describe("TILO-T-WORLD playback", () => {
  it("uses the design's three paces", () => {
    expect(STEP_MS).toEqual({ "1x": 2200, "2x": 1100, catch: 260 });
  });

  it("is not offered while the run is still going", async () => {
    const m = await open(run(false));
    expect(m.container.querySelector(".tw-play")).toBeNull();
  });

  it("1x steps one recorded event every 2200 ms from the start and rests at the end", async () => {
    const m = await open();
    press(m, "1×");
    expect(getReplayPoint("w_live")).toBe(0);
    await tick(2200);
    expect(getReplayPoint("w_live")).toBe(1);
    await tick(2200);
    expect(getReplayPoint("w_live")).toBe(2);
    await tick(2200);
    await tick(2200);
    await tick(2200);
    expect(getReplayPoint("w_live")).toBe(4);
    expect(m.container.querySelector('[aria-pressed="true"]')?.textContent).toContain("Pause");
  });

  it("2x halves the wait, and Pause holds where it is", async () => {
    const m = await open();
    press(m, "2×");
    await tick(1100);
    expect(getReplayPoint("w_live")).toBe(1);
    press(m, "Pause");
    await tick(5000);
    expect(getReplayPoint("w_live")).toBe(1);
  });

  it("Catch up runs at 260 ms and falls back to 1x at the end of the record", () => {
    expect(afterStep("catch", 3, 4)).toEqual({ index: 4, speed: "catch" });
    expect(afterStep("catch", 4, 4)).toEqual({ index: 4, speed: "1x" });
    expect(afterStep("1x", 4, 4)).toEqual({ index: 4, speed: "paused" });
    expect(afterStep("paused", 2, 4)).toEqual({ index: 2, speed: "paused" });
  });

  it("Whole run puts the stage back on the full record", async () => {
    const m = await open();
    press(m, "1×");
    await tick(2200);
    press(m, "Whole run");
    expect(getReplayPoint("w_live")).toBeNull();
  });
});
