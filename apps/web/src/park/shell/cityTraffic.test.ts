import { describe, expect, it } from "vitest";
import { fakeEnv, serialiseH } from "../../../test-support/park/engineProto";
import { createPark } from "../engines/park";
import { createWorld } from "../engines/world";
import { type Body, CityTraffic, type Route } from "./cityTraffic";

const walker = (x: number, y: number, end = 240): Route => ({
  kind: "walker",
  x,
  y,
  start: 0,
  end,
  speed: 16,
  halfX: 7,
  halfY: 7,
});

interface Tree {
  props: Record<string, unknown> | null;
  children: unknown[];
}
function routesOf(tree: unknown): Route[] {
  const routes: Route[] = [];
  const visit = (node: unknown): void => {
    if (Array.isArray(node)) {
      node.forEach(visit);
      return;
    }
    if (!node || typeof node !== "object") return;
    const n = node as Tree;
    const route = n.props?.["data-city-route"];
    if (typeof route === "string") routes.push(JSON.parse(route));
    n.children?.forEach(visit);
  };
  visit(tree);
  return routes;
}
const draw = (seed: number, still = false) =>
  createPark(serialiseH, createWorld, fakeEnv as never).scene({
    w: 1600,
    h: 1000,
    vw: 1240,
    seed,
    avoid: true,
    still,
  });
for (const seed of [1, 7, 23]) {
  it(`WEB_MOTION_1 real scene seed ${seed} keeps every footprint clear for 10 seconds`, () => {
    const scene = draw(seed).el as Tree;
    const routes = routesOf(scene);
    const standing = JSON.parse(String(scene.props?.["data-city-standing"])) as Body[];
    expect(routes.length).toBeGreaterThan(3);
    expect(standing.length).toBeGreaterThan(0);
    const traffic = new CityTraffic(routes, standing);
    const apart = (a: Body, b: Body) =>
      Math.abs(a.x - b.x) >= a.halfX + b.halfX || Math.abs(a.y - b.y) >= a.halfY + b.halfY;
    for (let tick = 0; tick < 600; tick++) {
      traffic.step();
      traffic.positions.forEach((p, i) => {
        for (const s of standing) expect(apart(p, s)).toBe(true);
        for (const q of traffic.positions.slice(i + 1)) expect(apart(p, q)).toBe(true);
      });
    }
  });
}
it("WEB_MOTION_1 still scenes expose no traffic routes and retain their frozen positions", () => {
  expect(routesOf(draw(23, true).el)).toEqual([]);
  expect(draw(23, true).el).toEqual(draw(23, true).el);
});
const car = (x: number, y: number): Route => ({
  ...walker(x, y),
  kind: "car",
  speed: 60,
  halfX: 12,
  halfY: 6,
});
const cells = (x: number, y: number) => `${Math.floor(x / 4)},${Math.floor(y / 4)}`;

describe("WEB_MOTION_1 city occupancy", () => {
  for (const seed of [1, 7, 23]) {
    it(`WEB_MOTION_1 vehicle yields without overlapping a walker for 30 seconds, seed ${seed}`, () => {
      const traffic = new CityTraffic([car(seed, 20), walker(55 + seed, 20)], []);
      let slowed = false;
      let resumed = false;
      let stopped = false;
      for (let tick = 0; tick < 1800; tick++) {
        traffic.step();
        const [vehicle, person] = traffic.positions;
        if (!vehicle || !person) throw new Error("missing movers");
        expect(Math.abs(vehicle.x - person.x) >= 19 || Math.abs(vehicle.y - person.y) >= 13).toBe(
          true,
        );
        slowed ||= vehicle.speed < 60;
        stopped ||= vehicle.speed === 0;
        resumed ||= slowed && vehicle.speed === 60;
      }
      expect(slowed).toBe(true);
      expect(stopped).toBe(true);
      expect(resumed).toBe(true);
    });
  }
  it("WEB_MOTION_1 walker paths around static occupancy and walkers never share a tile", () => {
    const traffic = new CityTraffic(
      [walker(0, 20), walker(30, 20)],
      [{ x: 80, y: 20, halfX: 8, halfY: 8 }],
    );
    let passed = false;
    for (let tick = 0; tick < 1200; tick++) {
      traffic.step();
      const tiles = new Set<string>();
      for (const p of traffic.positions) {
        expect(Math.abs(p.x - 80) >= 15 || Math.abs(p.y - 20) >= 15).toBe(true);
        expect(tiles.has(cells(p.x, p.y))).toBe(false);
        tiles.add(cells(p.x, p.y));
        passed ||= p.x > 100;
      }
    }
    expect(passed).toBe(true);
  });
  it("WEB_MOTION_1 equal seeded routes give equal positions at every tick", () => {
    const routes = [car(7, 20), walker(62, 20), walker(34, 60)];
    const a = new CityTraffic(routes, []);
    const b = new CityTraffic(routes, []);
    for (let tick = 0; tick < 600; tick++) {
      a.step();
      b.step();
      expect(a.positions).toEqual(b.positions);
    }
  });
});
