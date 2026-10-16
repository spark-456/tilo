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

it("FR_POOL_01_task_waits_for_world_started_and_names_world_planned", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "task", events: [], children: null }));
  await settle();
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();
  mounted.render(createElement(PoolLoader, { kind: "task", events: [{ type: "world.started" }], children: null }));
  await settle();
  expect(mounted.container.textContent).toContain("world.started");
  expect(mounted.container.querySelector('[aria-busy="true"]')).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(2600));
  expect(mounted.container.textContent).toContain("world.planned");
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
