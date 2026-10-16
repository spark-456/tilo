// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, createElement } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { settle } from "../../park/pages/Team/testApp";
import { PoolLoader } from "./PoolLoader";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("FR_POOL_01_task_waits_for_world_started_and_names_world_planned", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "task", events: [], children: null }));
  await settle();
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();
  mounted.render(createElement(PoolLoader, { kind: "task", events: [{ type: "world.started" }], children: null }));
  await settle();
  await act(async () => vi.advanceTimersByTimeAsync(300));
  expect(mounted.container.textContent).toContain("world.started");
  expect(mounted.container.querySelector('[aria-busy="true"]')).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(2600));
  expect(mounted.container.textContent).toContain("world.planned");
});

it("CX_T_RUN_batched_started_and_planned_events_keep_the_loader_for_slow_runs", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "task", events: [], children: null }));
  await settle();
  mounted.render(createElement(PoolLoader, {
    kind: "task",
    events: [
      { type: "world.started", ts: "2026-10-16T10:00:00.000Z" },
      { type: "world.planned", ts: "2026-10-16T10:00:00.400Z" },
    ],
    children: null,
  }));
  await settle();
  expect(mounted.container.querySelector("[data-phase='leap']")).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(2600));
  expect(mounted.container.querySelector("[data-phase='sink']")).not.toBeNull();
});

it("CX_T_RUN_quick_started_and_planned_events_skip_the_pool_overlay", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "task", events: [], children: null }));
  await settle();
  mounted.render(createElement(PoolLoader, {
    kind: "task",
    events: [
      { type: "world.started", ts: "2026-10-16T10:00:00.000Z" },
      { type: "world.planned", ts: "2026-10-16T10:00:00.299Z" },
    ],
    children: null,
  }));
  await settle();
  expect(mounted.container.querySelector("[data-testid='tt-pool-host']")?.textContent).not.toContain("world.started");
  expect(mounted.container.querySelector("[data-testid='tt-pool-host'] [data-phase]")).toBeNull();
});

it("FR_POOL_01_site_waits_300ms_before_showing", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "site", loading: true, children: null }));
  await settle();
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(301));
  expect(mounted.container.querySelector('[role="status"]')).not.toBeNull();
});

it("FR_POOL_01_site_finishing_before_300ms_never_shows_overlay", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "site", loading: true, children: null }));
  await settle();
  await act(async () => vi.advanceTimersByTimeAsync(299));
  mounted.render(createElement(PoolLoader, { kind: "site", loading: false, children: null }));
  await settle();
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();
});

it("CX_POOL_2_finished_page_load_sinks_without_covering_the_ready_page_for_seconds", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "site", loading: true, children: null }));
  await settle();
  await act(async () => vi.advanceTimersByTimeAsync(301));
  mounted.render(createElement(PoolLoader, { kind: "site", loading: false, children: null }));
  await settle();
  expect(mounted.container.querySelector("[data-phase=sink]")).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(251));
  expect(mounted.container.querySelector(".tt-pool-overlay")).toBeNull();
});

it("CX_POOL_2_pool_motion_avoids_page_repaints_and_animates_the_real_overlay", () => {
  const css = readFileSync(join(__dirname, "PoolLoader.css"), "utf8");
  const motion = readFileSync(join(__dirname, "motion.css"), "utf8");
  expect(css).not.toMatch(/\bfilter:|\boffset-path:/);
  expect(motion.match(/@keyframes tSwim\{[^}]*\}/)?.[0]).not.toContain("offset-distance");
  expect(motion).toMatch(/\.tt-pool-overlay\{animation:/);
});
