/**
 * TILO-T-WORLD step 3 (FR-WLD-06, HR-3): hover, the lit agents of a clicked message, the open agent panel and the
 * camera's fly-to are display state: held per world, never an event, and they move nothing in the world.
 */
import { afterEach, expect, test, vi } from "vitest";
import {
  type Probe,
  flyTo,
  getSpotlight,
  onFly,
  openAgent,
  registerProbe,
  resetSpotlights,
  setHover,
  setLit,
  subscribeSpotlight,
} from "./spotlight";

afterEach(() => resetSpotlights());

test("FR-WLD-06 TILO-T-WORLD spotlight: hovering lights one agent and remembers where the pointer is", () => {
  setHover("w1", "A_s1", { x: 40, y: 50 });
  expect(getSpotlight("w1").hover).toBe("A_s1");
  expect(getSpotlight("w1").point).toEqual({ x: 40, y: 50 });
  setHover("w1", null, null);
  expect(getSpotlight("w1").hover).toBeNull();
});

test("FR-WLD-06 TILO-T-WORLD spotlight: one world's spotlight never shows in another's", () => {
  setHover("w1", "A_s1", { x: 1, y: 1 });
  setLit("w1", ["A_l1", "A_s1"]);
  expect(getSpotlight("w2")).toEqual({ hover: null, point: null, lit: [], opened: null });
});

test("FR-WLD-06 TILO-T-WORLD spotlight: subscribers hear a change once, and not a no-op", () => {
  const seen = vi.fn();
  const off = subscribeSpotlight(seen);
  setHover("w1", "A_s1", { x: 1, y: 1 });
  setHover("w1", "A_s1", { x: 1, y: 1 });
  expect(seen).toHaveBeenCalledTimes(1);
  setLit("w1", ["A_l1"]);
  setLit("w1", ["A_l1"]);
  expect(seen).toHaveBeenCalledTimes(2);
  off();
  openAgent("w1", "A_s1");
  expect(seen).toHaveBeenCalledTimes(2);
});

test("FR-WLD-06 TILO-T-WORLD spotlight: clicking an agent opens its panel and closing clears it", () => {
  openAgent("w1", "A_s1");
  expect(getSpotlight("w1").opened).toBe("A_s1");
  openAgent("w1", null);
  expect(getSpotlight("w1").opened).toBeNull();
});

test("FR-WLD-06 TILO-T-WORLD spotlight: the stage's probe answers which agent is under a point and where an id is", () => {
  const probe: Probe = {
    agentAt: (x, y) => (x === 10 && y === 20 ? "A_s1" : null),
    locate: (id) => (id === "B2" ? { x: 100, y: 80 } : null),
  };
  const off = registerProbe("w1", probe);
  expect(getSpotlight("w1")).toBeDefined();
  expect(registerProbe.get("w1")?.agentAt(10, 20)).toBe("A_s1");
  expect(registerProbe.get("w1")?.locate("B2")).toEqual({ x: 100, y: 80 });
  off();
  expect(registerProbe.get("w1")).toBeUndefined();
});

test("FR-WLD-04 TILO-T-WORLD spotlight: a Story or chat click flies the camera to an object of that world only", () => {
  const here = vi.fn();
  const other = vi.fn();
  const offHere = onFly("w1", here);
  const offOther = onFly("w2", other);
  flyTo("w1", "B2", 900);
  expect(here).toHaveBeenCalledWith("B2", 900);
  expect(other).not.toHaveBeenCalled();
  offHere();
  offOther();
});
