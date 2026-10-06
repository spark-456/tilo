// WEB-3b test support: a fast stand-in for the city scene. The real `scene()` draws a 1600x1000 city (seconds
// in happy-dom); every other engine call (agents, buildings, worlds, the kit's icons) stays real. Wire it in a
// test file with:
//   vi.mock("../engines/park", async () => (await import("../../../test-support/park/shellEngine")).parkMock());
// `sceneSpy` records each `scene(opts)` call, so a test can count how often the backdrop builds the city.
import { createElement } from "react";
import { vi } from "vitest";
import type { Spot } from "../../src/park/engines/types";

export const SCENE_SPOTS: Spot[] = [
  { x: 1000, y: 420, area: 5, st: "a" },
  { x: 820, y: 640, area: 6, st: "b" },
  { x: 900, y: 250, area: 3, st: "c" },
  { x: 300, y: 300, area: 9, st: "d" },
];

let built = 0;
export const sceneSpy = vi.fn((_o?: unknown) => {
  built += 1;
  return {
    el: createElement("div", { "data-testid": "fake-scene", "data-build": String(built) }),
    spots: SCENE_SPOTS,
  };
});

export async function parkMock() {
  const actual =
    await vi.importActual<typeof import("../../src/park/engines/park")>("../../src/park/engines/park");
  return {
    ...actual,
    createPark: (...args: Parameters<typeof actual.createPark>) => ({
      ...actual.createPark(...args),
      scene: sceneSpy,
    }),
  };
}
