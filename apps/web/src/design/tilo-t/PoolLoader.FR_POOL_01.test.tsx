// @vitest-environment happy-dom
import { act, createElement } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { settle } from "../../park/pages/Team/testApp";
import { PoolLoader } from "./PoolLoader";
import { ASSET } from "./poolAssets";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const page = createElement("p", null, "World is visible");

it("FR_POOL_01_task_card_appears_on_world_started_and_never_covers_the_page", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "task", events: [], children: page }));
  await settle();
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();
  mounted.render(createElement(PoolLoader, { kind: "task", events: [{ type: "world.started" }], children: page }));
  await settle();
  const card = mounted.container.querySelector("[data-testid='tt-plan-card']");
  expect(card?.textContent).toContain("Director is planning");
  expect(card?.textContent).toContain("world.planned");
  // the world stays mounted, sharp and clickable: no overlay, scrim or blur
  expect(mounted.container.textContent).toContain("World is visible");
  expect(mounted.container.querySelector(".tt-pool-overlay, .tt-pool-scrim")).toBeNull();
  expect(mounted.container.querySelector(".tt-pool-page--covered")).toBeNull();
  expect(mounted.container.querySelector('[aria-busy="true"]')).not.toBeNull();
});

it("FR_POOL_01_task_card_goes_on_world_planned_or_world_failed", async () => {
  const started = { type: "world.started" };
  const mounted = mount(createElement(PoolLoader, { kind: "task", events: [started], children: page }));
  await settle();
  expect(mounted.container.querySelector("[data-testid='tt-plan-card']")).not.toBeNull();
  mounted.render(createElement(PoolLoader, { kind: "task", events: [started, { type: "world.planned" }], children: page }));
  await settle();
  expect(mounted.container.querySelector("[data-testid='tt-plan-card']")).toBeNull();
  mounted.render(createElement(PoolLoader, { kind: "task", events: [started, { type: "world.failed" }], children: page }));
  await settle();
  expect(mounted.container.querySelector("[data-testid='tt-plan-card']")).toBeNull();
});

it("FR_POOL_01_task_card_says_so_when_planning_takes_long", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "task", events: [{ type: "world.started" }], children: page }));
  await settle();
  expect(mounted.container.textContent).not.toContain("Taking longer");
  await act(async () => vi.advanceTimersByTimeAsync(45_000));
  expect(mounted.container.textContent).toContain("Taking longer than usual");
  expect(mounted.container.querySelector(".tt-pool-overlay")).toBeNull();
});

it("FR_POOL_01_site_waits_300ms_before_showing", async () => {
  vi.useFakeTimers();
  const mounted = mount(createElement(PoolLoader, { kind: "site", loading: true, children: null }));
  await settle();
  expect(mounted.container.querySelector('[role="status"]')).toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(301));
  expect(mounted.container.querySelector('[role="status"]')).not.toBeNull();
  expect(mounted.container.querySelector(`img[src="${ASSET}"]`)).not.toBeNull();
  expect(mounted.container.querySelector(".tt-pool__water")).toBeNull();
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
