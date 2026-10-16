// @vitest-environment happy-dom
// UI-10 W18, kept through STUDIO-3: one card grid ("Your worlds") replaces the three size sections.
import { afterEach, expect, it, vi } from "vitest";
import { cleanup } from "../../../../test-support/park/componentsHarness";
import {
  cardIds,
  flush,
  renderWorlds,
  search,
  tabCounts,
  typeInto,
  worldsApi,
} from "../../../../test-support/park/worldsHarness";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const GRID = "Your worlds";

it("UI-10 W18 whitespace search preserves worlds and tab counts", async () => {
  const { c } = await renderWorlds();
  const counts = tabCounts(c);
  const ids = cardIds(c, GRID);
  typeInto(search(c), "   \t  ");
  expect(cardIds(c, GRID)).toEqual(ids);
  expect(tabCounts(c)).toEqual(counts);
  expect(c.textContent).not.toContain("No worlds match");
  typeInto(search(c), "  INVOICE  ");
  expect(cardIds(c, GRID)).toEqual(["invoice"]);
  expect(tabCounts(c).All).toBe(1);
});

it("UI-10 W18 loading reserves card grid and replaces skeleton after data arrives", async () => {
  const api = worldsApi();
  const result = await api.getWorlds({}, []);
  let resolve!: (value: typeof result) => void;
  api.getWorlds = vi.fn(
    () =>
      new Promise<typeof result>((done) => {
        resolve = done;
      }),
  );
  const { c } = await renderWorlds({ api });
  const loading = c.querySelector('[role="status"][data-testid="tt-loading"]');
  expect(loading).not.toBeNull();
  expect(loading?.textContent).toContain("Loading worlds");
  expect(loading?.querySelectorAll(".tt-sk--card")).toHaveLength(6);
  expect(loading?.querySelector("a,button")).toBeNull();
  resolve(result);
  await flush();
  expect(c.querySelector('[data-testid="tt-loading"]')).toBeNull();
  expect(cardIds(c, GRID).slice(0, 2)).toEqual(["k1", "hires"]);
});

it("UI-10 W18 loading skeleton clears on failure", async () => {
  const api = worldsApi();
  api.getWorlds = vi.fn(() => Promise.reject(new Error("offline")));
  const { c } = await renderWorlds({ api });
  expect(c.querySelector('[data-testid="tt-loading"]')).toBeNull();
  expect(c.textContent).toContain("Worlds data is unavailable");
});

it("UI-10 W18 staged cards reserve all grid slots before expensive art renders", async () => {
  vi.stubGlobal("CSSAnimation", class {});
  vi.useFakeTimers();
  const { c } = await renderWorlds();
  const grid = c.querySelector(`section[aria-label="${GRID}"] .park-worlds-grid`);
  expect(grid).not.toBeNull();
  expect(grid?.children).toHaveLength(11);
  expect(grid?.querySelectorAll(".park-worlds-skeleton")).toHaveLength(11);
});
