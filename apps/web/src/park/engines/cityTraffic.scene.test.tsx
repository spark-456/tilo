// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { serialiseH } from "../../../test-support/park/engineProto";
import { useCityMotion } from "../shell/cityMotion";
import { backdropScene } from "../shell/scene";
import * as traffic from "./cityTraffic";
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

it("WEB_MOTION_1 built city has at most two fading movers throughout its cycle", () => {
  for (const seed of [0, 1, 7, 23]) {
    const draw = () =>
      seed === 0 ? backdropScene("day", "lively").el : engine().scene({ ...opts, seed }).el;
    const styles = movers(draw());
    expect(styles.length).toBeGreaterThan(3);
    const clocks = styles.map((s) => {
      const clock = /tiloFade 15s linear\(([^)]+)\) (-?[\d.]+)s infinite/.exec(s.animation ?? "");
      expect(clock).not.toBeNull();
      const stops = (clock?.[1] ?? "")
        .split(",")
        .map((x) => x.trim().split(/\s+/).map(Number.parseFloat));
      return { delay: Number(clock?.[2]), edge: (stops[2]?.[1] ?? 0) / 100 };
    });
    for (let ms = 0; ms < 15000; ms += 5) {
      const fading = clocks.filter(({ delay, edge }) => {
        const phase = ((((ms / 1000 - delay) % 15) + 15) % 15) / 15;
        return phase < edge || phase > 1 - edge;
      });
      expect(fading.length, `seed ${seed}, ${ms}ms`).toBeLessThanOrEqual(2);
    }
    expect(styles).toEqual(movers(draw()));
  }
});
it("WEB_MOTION_1 built scene stagger retains zero car-walker and same-kind overlaps", () => {
  const recorded = new Map<traffic.Route, traffic.Body[]>();
  const compile = traffic.compileTraffic;
  vi.spyOn(traffic, "compileTraffic").mockImplementation((routes, standing, lanesOnly) => {
    const frames = compile(routes, standing, lanesOnly);
    routes.forEach((route, id) =>
      recorded.set(
        route,
        frames.map((frame) => frame[id] as traffic.Body),
      ),
    );
    return frames;
  });
  const stagger = vi.spyOn(traffic, "staggerTraffic");
  const styles = movers(engine().scene(opts).el);
  const routes = stagger.mock.calls[0]?.[0];
  const clocks = stagger.mock.results[0]?.value as ReturnType<typeof traffic.staggerTraffic>;
  expect(routes?.length).toBe(styles.length);
  const emitted = styles
    .map((s) => Number(/\) (-?[\d.]+)s infinite/.exec(s.animation ?? "")?.[1]))
    .sort((a, b) => a - b);
  expect(emitted).toEqual(clocks.map((c) => Number(c.delay.toFixed(8))).sort((a, b) => a - b));
  if (!routes) throw new Error("missing actual scene routes");
  for (let ms = 0; ms < 15000; ms += 25) {
    const positions = routes.map((route, id) => {
      const tick = ((((ms / 1000 - (clocks[id]?.delay ?? 0)) % 15) + 15) % 15) * 4;
      const frames = recorded.get(route);
      const a = frames?.[Math.floor(tick)];
      const b = frames?.[Math.min(59, Math.floor(tick) + 1)];
      if (!a || !b) throw new Error("missing actual scene frame");
      return { ...a, x: a.x + (b.x - a.x) * (tick % 1) };
    });
    for (let i = 0; i < positions.length; i++)
      for (let j = i + 1; j < positions.length; j++) {
        const a = positions[i];
        const b = positions[j];
        if (!a || !b) throw new Error("missing mover");
        expect(
          Math.abs(a.x - b.x) >= a.halfX + b.halfX || Math.abs(a.y - b.y) >= a.halfY + b.halfY,
        ).toBe(true);
      }
  }
});

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
