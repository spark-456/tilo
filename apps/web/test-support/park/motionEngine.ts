// WEB-MOTION-1 test support: the shellEngine stand-in for the city scene, plus the options each build was
// asked for written on the scene element (`data-still`, `data-k`), so a test reads what is ON SCREEN and
// does not depend on which keys an earlier test already filled in the document-wide cache.
// Wire it with:
//   vi.mock("../engines/park", async () => (await import("../../../test-support/park/motionEngine")).parkMock());
import { createElement } from "react";
import { vi } from "vitest";

let built = 0;
export const sceneSpy = vi.fn((o?: unknown) => {
  built += 1;
  const opts = (o ?? {}) as { night?: boolean; still?: boolean; k?: number };
  return {
    el: createElement("div", {
      "data-testid": "fake-scene",
      "data-build": String(built),
      "data-night": String(opts.night === true),
      "data-still": String(opts.still === true),
      "data-k": String(opts.k ?? 1),
    }),
    spots: [],
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
