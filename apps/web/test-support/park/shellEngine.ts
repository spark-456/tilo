// WEB-3b test support: a fast stand-in for the city scene. The real `scene()` draws a 1600x1000 city (about
// 300 ms in happy-dom); every other engine call (agents, buildings, worlds, the kit's icons) stays real. Wire it
// in a test file with:
//   vi.mock("../engines/park", async () => (await import("../../../test-support/park/shellEngine")).parkMock());
// `sceneSpy` records each `scene(opts)` call, so a test can count how often the city is built, and
// `sceneConfig.spots` is what the next build returns as its free spots (the scene's second result).
import { createElement } from "react";
import { vi } from "vitest";
import type { Spot } from "../../src/park/engines/types";

export const sceneConfig: { spots: Spot[] } = { spots: [] };

let built = 0;
export const sceneSpy = vi.fn((o?: unknown) => {
  built += 1;
  const night = (o as { night?: boolean } | undefined)?.night === true;
  return {
    el: createElement("div", {
      "data-testid": "fake-scene",
      "data-build": String(built),
      "data-night": String(night),
    }),
    spots: sceneConfig.spots,
  };
});

export async function parkMock() {
  const actual = await vi.importActual<typeof import("../../src/park/engines/park")>(
    "../../src/park/engines/park",
  );
  return {
    ...actual,
    createPark: (...args: Parameters<typeof actual.createPark>) => ({
      ...actual.createPark(...args),
      scene: sceneSpy,
    }),
  };
}
