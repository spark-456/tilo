import { describe, expect, it } from "vitest";
import { CityTraffic, type Route, compileTraffic } from "./cityTraffic";

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

const car = (x: number, y: number): Route => ({
  ...walker(x, y),
  kind: "car",
  speed: 60,
  halfX: 12,
  halfY: 6,
});
const cells = (x: number, y: number) => `${Math.floor(x / 4)},${Math.floor(y / 4)}`;

describe("WEB_MOTION_1 city occupancy", () => {
  it("WEB_MOTION_1 compiled CSS segments and repeated schedules remain collision free", () => {
    for (const seed of [1, 7, 23]) {
      const routes = [car(seed, 20), walker(55 + seed, 20)];
      const frames = compileTraffic(routes, []);
      expect(frames).toEqual(compileTraffic(routes, []));
      expect(frames).toHaveLength(61);
      expect(frames.at(-1)).toEqual(frames[0]);
      for (let i = 0; i < 59; i++) {
        const a = frames[i];
        const b = frames[i + 1];
        if (!a || !b) throw new Error("missing frame");
        for (const f of [0, 0.25, 0.5, 0.75, 1]) {
          const ps = a.map((p, id) => {
            const q = b[id];
            if (!q) throw new Error("missing mover");
            return { x: p.x + (q.x - p.x) * f, y: p.y + (q.y - p.y) * f };
          });
          const [vehicle, person] = ps;
          if (!vehicle || !person) throw new Error("missing movers");
          expect(Math.abs(vehicle.x - person.x) >= 19 || Math.abs(vehicle.y - person.y) >= 13).toBe(
            true,
          );
        }
      }
    }
  });
  for (const seed of [1, 7, 23]) {
    it(`WEB_MOTION_1 vehicle yields without overlapping a walker for 20 seconds, seed ${seed}`, () => {
      const traffic = new CityTraffic([car(seed, 20), walker(55 + seed, 20)], []);
      let slowed = false;
      let resumed = false;
      let stopped = false;
      for (let tick = 0; tick < 1200; tick++) {
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
