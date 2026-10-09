// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { serialiseH } from "../../../test-support/park/engineProto";
import { useCityMotion } from "../shell/cityMotion";
import { backdropScene } from "../shell/scene";
import * as lanes from "./lanes";
import { createPark } from "./park";
import type { H } from "./types";
import { createWorld } from "./world";

vi.mock("../shell/kit", async () => {
  const { createKit } = await import("./kit");
  const { serialiseH } = await import("../../../test-support/park/engineProto");
  const kit = createKit(serialiseH as H, {
    plans: () => ({}),
    env: { createObjectURL: () => "blob:scene" },
  });
  return { parkKit: () => kit };
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
type Style = Record<string, string>;
function movers(tree: unknown, carsOnly = false): Style[] {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap((child) => movers(child, carsOnly));
  const node = tree as { props?: { style?: Style; children?: unknown }; children?: unknown };
  const s = node.props?.style;
  const first = (Array.isArray(node.children) ? node.children[0] : null) as { tag?: string } | null;
  return [
    ...(s?.willChange === "transform" && (!carsOnly || first?.tag === "img") ? [s] : []),
    ...movers(node.children ?? node.props?.children, carsOnly),
  ];
}
const engine = () =>
  createPark(serialiseH as H, createWorld, { createObjectURL: () => "blob:scene" });
const opts = { w: 1440, h: 900, seed: 23, avoid: true, traffic: true };

it("WEB_MOTION_1 built backdrop schedules hide every visible reset", () => {
  const styles = movers(backdropScene("day", "lively").el);
  expect(styles.length).toBeGreaterThan(3);
  for (const s of styles) {
    expect(s.animation).toContain("mvXY 15s linear(");
    const fade = /tiloFade 15s linear\(([^)]+)\)/.exec(s.animation ?? "");
    expect(fade, "a reset may occur mid-lane only while the layer is transparent").not.toBeNull();
    const stops = (fade?.[1] ?? "")
      .split(",")
      .map((stop) => stop.trim().split(/\s+/).map(Number.parseFloat));
    // tiloFade interpolates underlying opacity 1 to 0: output 1 means fully transparent.
    expect(stops[0]?.[0]).toBe(1);
    expect(stops[1]?.[0]).toBe(1);
    expect(stops.at(-2)?.[0]).toBe(1);
    expect(stops.at(-1)?.[0]).toBe(1);
    expect(stops[1]?.[1]).toBeGreaterThan((0.001 / 15) * 100);
    expect(stops.at(-2)?.[1]).toBeLessThan((14.99 / 15) * 100);
    expect(stops.some(([value]) => value === 0)).toBe(true);
  }
});
it("WEB_MOTION_1 actual still and reduced-motion backdrop keeps frozen movers", () => {
  const media = { matches: true, addEventListener: () => {}, removeEventListener: () => {} };
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => media),
  );
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  let motion: "lively" | "calm" | "still" = "lively";
  function Probe() {
    motion = useCityMotion("lively", 1440).motion;
    return null;
  }
  const root = createRoot(document.createElement("div"));
  act(() => root.render(<Probe />));
  expect(motion).toBe("still");
  for (const s of movers(backdropScene("day", motion).el)) {
    expect(s.animation).toBeUndefined();
    expect(s.transform).toMatch(/^translate\(/);
  }
  act(() => root.unmount());
  vi.unstubAllGlobals();
});
it("WEB_MOTION_1 a walker across a car lane changes the built scene schedule", () => {
  const normal = movers(engine().scene(opts).el, true).map((s) => s.animation);
  const assign = lanes.assignLane;
  let carLane = 0;
  vi.spyOn(lanes, "assignLane").mockImplementation((pref, half, range, taken) => {
    const lane = assign(pref, half, range, taken);
    if (half === lanes.CAR_HALF && lane !== null) carLane = lane;
    return half === lanes.WALKER_HALF ? carLane : lane;
  });
  const crossing = movers(engine().scene(opts).el, true).map((s) => s.animation);
  expect(crossing).toHaveLength(normal.length);
  expect(crossing.filter((s) => s?.includes("linear("))).not.toHaveLength(0);
  expect(crossing).not.toEqual(normal);
});
it("WEB_MOTION_1 unsupported easing retains the original route motion", () => {
  const supports = vi.fn(() => false);
  vi.stubGlobal("CSS", { supports });
  const styles = movers(engine().scene(opts).el);
  expect(supports).toHaveBeenCalledWith("animation", "mvXY 1s linear(0,1)");
  expect(styles.length).toBeGreaterThan(3);
  for (const s of styles) {
    expect(s.animation).toMatch(/^mvXY .*s linear .*s infinite$/);
    expect(s.animation).not.toContain("linear(");
  }
});
