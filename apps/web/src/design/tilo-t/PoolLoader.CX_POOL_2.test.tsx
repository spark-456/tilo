// @vitest-environment happy-dom
import { act, createElement } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../test-support/park/componentsHarness";
import { PoolLoader } from "./PoolLoader";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("CX_POOL_2_site_covers_the_first_paint_with_workspace_connection_copy", () => {
  const mounted = mount(
    createElement(PoolLoader, { kind: "site", loading: true, children: null }),
  );
  expect(mounted.container.querySelector(".tt-pool-overlay [role='status']")).not.toBeNull();
  expect(mounted.container.textContent).toContain("Fetching your workspace");
});

it("CX_POOL_2_fast_site_completion_waits_for_the_leap_and_back_to_water_cycle", async () => {
  vi.useFakeTimers();
  const mounted = mount(
    createElement(PoolLoader, { kind: "site", loading: true, children: null }),
  );
  mounted.render(createElement(PoolLoader, { kind: "site", loading: false, children: null }));
  await act(async () => vi.advanceTimersByTimeAsync(2600));
  expect(mounted.container.querySelector(".tt-pool-overlay[data-phase='sink']")).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(1999));
  expect(mounted.container.querySelector(".tt-pool-overlay")).not.toBeNull();
  await act(async () => vi.advanceTimersByTimeAsync(1));
  expect(mounted.container.querySelector(".tt-pool-overlay")).toBeNull();
});

it("CX_POOL_2_reduced_motion_reveals_a_fast_completion_after_a_short_fade", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const mounted = mount(
    createElement(PoolLoader, { kind: "site", loading: true, children: null }),
  );
  mounted.render(createElement(PoolLoader, { kind: "site", loading: false, children: null }));
  await act(async () => vi.advanceTimersByTimeAsync(250));
  await act(async () => vi.advanceTimersByTimeAsync(250));
  expect(mounted.container.querySelector(".tt-pool-overlay")).toBeNull();
});
