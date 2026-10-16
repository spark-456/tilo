// @vitest-environment happy-dom
import { act, createElement } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { settle } from "../../park/pages/Team/testApp";
import { PoolLoader } from "./PoolLoader";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const NOW = new Date("2026-10-16T12:00:00.000Z");
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString();

it("FR_POOL_01_NO_REPLAY_a_world_that_ended_earlier_opens_with_no_loader", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  const events = [
    { type: "world.started", ts: ago(60 * 60_000) },
    { type: "world.failed", ts: ago(59 * 60_000) },
  ];
  const mounted = mount(createElement(PoolLoader, { kind: "task", events, children: null }));
  await settle();
  await act(async () => vi.advanceTimersByTimeAsync(20_000));
  expect(mounted.container.querySelector(".tt-pool-overlay")).toBeNull();
});

it("FR_POOL_01_NO_REPLAY_a_run_that_just_ended_plays_once_and_never_returns", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
  const events = [
    { type: "world.started", ts: ago(3_000) },
    { type: "world.failed", ts: ago(1_000) },
  ];
  const mounted = mount(createElement(PoolLoader, { kind: "task", events, children: null }));
  await settle();
  expect(mounted.container.querySelector(".tt-pool-overlay")).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(2_600));
  await act(async () => vi.advanceTimersByTimeAsync(2_000));
  expect(mounted.container.querySelector(".tt-pool-overlay")).toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(30_000));
  expect(mounted.container.querySelector(".tt-pool-overlay")).toBeNull();
});
