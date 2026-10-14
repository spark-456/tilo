// @vitest-environment happy-dom
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

it("UI-10 W18 whitespace search preserves worlds and tab counts", async () => {
  const { c } = await renderWorlds();
  const counts = tabCounts(c);
  const ids = cardIds(c, "Cities");
  typeInto(search(c), "   \t  ");
  expect(cardIds(c, "Cities")).toEqual(ids);
  expect(tabCounts(c)).toEqual(counts);
  expect(c.textContent).not.toContain("No worlds match");
  typeInto(search(c), "  INVOICE  ");
  expect(cardIds(c, "Towns")).toEqual(["invoice"]);
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
  const loading = c.querySelector('[role="status"][aria-label="Loading worlds"]');
  expect(loading).not.toBeNull();
  expect(loading?.textContent).toContain("Loading worlds");
  expect(loading?.querySelector(".park-worlds-grid--city")).not.toBeNull();
  expect(loading?.querySelectorAll('[aria-hidden="true"] .park-worlds-card--city')).toHaveLength(3);
  expect(loading?.querySelector("a,button")).toBeNull();
  resolve(result);
  await flush();
  expect(c.querySelector('[aria-label="Loading worlds"]')).toBeNull();
  expect(cardIds(c, "Cities")).toEqual(["k1", "hires", "audit"]);
});

it("UI-10 W18 loading skeleton clears on failure", async () => {
  const api = worldsApi();
  api.getWorlds = vi.fn(() => Promise.reject(new Error("offline")));
  const { c } = await renderWorlds({ api });
  expect(c.querySelector('[aria-label="Loading worlds"]')).toBeNull();
  expect(c.textContent).toContain("Worlds data is unavailable");
});

it("UI-10 W18 staged cards reserve all grid slots before expensive art renders", async () => {
  vi.stubGlobal("CSSAnimation", class {});
  vi.useFakeTimers();
  const { c } = await renderWorlds();
  for (const [scale, count] of [
    ["city", 3],
    ["town", 4],
    ["village", 4],
  ] as const) {
    const grid = c.querySelector(`.park-worlds-grid--${scale}`);
    expect(grid).not.toBeNull();
    expect(grid?.children).toHaveLength(count);
    expect(grid?.querySelectorAll(".park-worlds-skeleton")).toHaveLength(count);
  }
});
