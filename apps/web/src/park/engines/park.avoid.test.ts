// FR-UX-12 / issue #588 (Home city polish): the city's cars and walkers keep out of each other's way and out
// of the agents standing at the buildings. The movers are linear loops along a road, so two movers whose
// lanes overlap sideways will meet sooner or later; the only avoidance that needs no new keyframe is to give
// each mover its own lane (a lateral offset across the road). `avoid: true` does that, deterministically,
// from the same seeded rng (the draws are the same, a mover with no free lane is not drawn). The default
// stays the prototype's drawing, so park.parity.test.ts and park.motion.test.ts are untouched.
import * as fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  type Engine,
  type Json,
  type TestH,
  call,
  canon,
  fakeEnv,
  serialiseH,
} from "../../../test-support/park/engineProto";
import { type Band, assignLane } from "./lanes";
import { createPark } from "./park";
import { createWorld } from "./world";

const SLOW = { timeout: 180_000 };
type MakePark = (h: TestH, makeWorld: typeof createWorld, env?: unknown) => Engine;
const portPark = (): Engine =>
  (createPark as unknown as MakePark)(serialiseH, createWorld, fakeEnv);

interface LaneRow {
  row: number;
  kind: "car" | "walker" | "standing";
  lane: number | null;
  pref: number;
  half: number;
}
interface Drawn {
  el: unknown;
  lanes?: LaneRow[];
}
const scene = (opts: Record<string, unknown>): Drawn => call(portPark(), "scene", opts) as Drawn;

const SEEDS = [23, 1, 7, 42, 99, 2024];
const BASE = { w: 1000, h: 700, still: false };

describe("FR-UX-12 lanes: assignLane picks a free lateral offset", () => {
  it("FR-UX-12 takes the preferred offset when it is free", () => {
    expect(assignLane(33, 5.5, [6, 40], [])).toBe(33);
  });

  it("FR-UX-12 moves to the nearest free offset beside a taken band, with a gap", () => {
    const taken: Band[] = [{ lo: 27, hi: 39 }];
    const lane = assignLane(33, 7, [2.5, 43.5], taken);
    expect(lane).not.toBeNull();
    const c = lane as number;
    expect(c + 7 <= 27 || c - 7 >= 39, "the walker clears the car").toBe(true);
  });

  it("FR-UX-12 returns null when nothing in range is free", () => {
    expect(assignLane(20, 7, [2.5, 43.5], [{ lo: -50, hi: 100 }])).toBeNull();
  });

  it("FR-UX-12 property: the lane is inside the range, clear of every taken band, and repeatable", () => {
    const band = fc
      .tuple(fc.integer({ min: -10, max: 50 }), fc.integer({ min: 1, max: 20 }))
      .map(([lo, w]): Band => ({ lo, hi: lo + w }));
    fc.assert(
      fc.property(
        fc.integer({ min: 0, max: 46 }),
        fc.constantFrom(5.5, 7.2),
        fc.array(band, { maxLength: 4 }),
        (pref, half, taken) => {
          const a = assignLane(pref, half, [2.5, 43.5], taken);
          expect(assignLane(pref, half, [2.5, 43.5], taken)).toBe(a);
          if (a === null) return;
          expect(a).toBeGreaterThanOrEqual(2.5);
          expect(a).toBeLessThanOrEqual(43.5);
          for (const t of taken) expect(a + half <= t.lo || a - half >= t.hi).toBe(true);
        },
      ),
      { numRuns: 200 },
    );
  });
});

describe("FR-UX-12 city: cars, walkers and standing agents never share a lane", () => {
  it(
    "FR-UX-12 with avoid, no two drawn things in one road row overlap sideways (several seeds, day and night)",
    SLOW,
    () => {
      let checked = 0;
      for (const seed of SEEDS) {
        for (const night of [false, true]) {
          const { lanes } = scene({ ...BASE, seed, night, avoid: true });
          expect(lanes, "avoid reports the lanes it chose").toBeDefined();
          const byRow = new Map<number, LaneRow[]>();
          for (const l of lanes as LaneRow[]) {
            if (l.lane === null) continue;
            byRow.set(l.row, [...(byRow.get(l.row) ?? []), l]);
          }
          for (const [row, list] of byRow) {
            for (let i = 0; i < list.length; i++)
              for (let j = i + 1; j < list.length; j++) {
                const a = list[i] as LaneRow;
                const b = list[j] as LaneRow;
                // two standing agents share the kerb at different places: they never move into each other
                if (a.kind === "standing" && b.kind === "standing") continue;
                const apart =
                  (a.lane as number) + a.half <= (b.lane as number) - b.half ||
                  (b.lane as number) + b.half <= (a.lane as number) - a.half;
                expect(apart, `seed ${seed} row ${row}: ${a.kind} and ${b.kind} overlap`).toBe(
                  true,
                );
                checked++;
              }
          }
        }
      }
      expect(checked, "the check saw real pairs").toBeGreaterThan(5);
    },
  );

  it(
    "FR-UX-12 the movers are the same draws: avoid only moves a lane or leaves a mover out",
    SLOW,
    () => {
      const runs = (tree: unknown): string[] => {
        const out: string[] = [];
        const walk = (x: Json): void => {
          if (Array.isArray(x)) x.forEach(walk);
          else if (x && typeof x === "object") {
            const s = (x as { props?: { style?: Record<string, Json> } }).props?.style;
            if (s && typeof s.animation === "string" && s.animation.startsWith("mvXY "))
              out.push(`${s.animation}|${String(s["--dx"])}|${String(s["--dy"])}`);
            for (const v of Object.values(x)) walk(v as Json);
          }
        };
        walk(canon(tree));
        return out.sort();
      };
      const plain = runs(scene({ ...BASE, seed: 23 }).el);
      const avoided = runs(scene({ ...BASE, seed: 23, avoid: true }).el);
      expect(avoided.length).toBeGreaterThan(3);
      expect(avoided.length).toBeLessThanOrEqual(plain.length);
      // every avoided mover has the prototype's duration, phase and travel
      const left = [...plain];
      for (const r of avoided) {
        const at = left.indexOf(r);
        expect(at, `mover ${r} is one of the prototype's`).toBeGreaterThanOrEqual(0);
        left.splice(at, 1);
      }
    },
  );

  it(
    "FR-UX-12 avoid really changes something (the prototype's lanes did overlap) and is repeatable",
    SLOW,
    () => {
      const a = scene({ ...BASE, seed: 23, avoid: true });
      const b = scene({ ...BASE, seed: 23, avoid: true });
      expect(canon(a.el)).toEqual(canon(b.el));
      expect(a.lanes).toEqual(b.lanes);
      const moved = (a.lanes as LaneRow[]).filter((l) => l.lane !== l.pref);
      expect(moved.length, "some mover left its prototype lane").toBeGreaterThan(0);
      expect(
        (a.lanes as LaneRow[]).some((l) => l.kind === "standing"),
        "the scene has standing agents to keep clear of",
      ).toBe(true);
    },
  );

  it("FR-UX-12 without avoid the drawing is the prototype's and reports no lanes", SLOW, () => {
    expect(scene({ ...BASE, seed: 23 }).lanes).toBeUndefined();
  });

  it("FR-UX-12 avoid keeps the pins (spots) and the sprite-cap structure", SLOW, () => {
    const plain = call(portPark(), "scene", { ...BASE, seed: 23 }) as { spots: unknown };
    const avoided = call(portPark(), "scene", { ...BASE, seed: 23, avoid: true }) as {
      spots: unknown;
      el: unknown;
    };
    expect(avoided.spots).toEqual(plain.spots);
    const root = canon(avoided.el) as unknown as { children: Json[] };
    for (const c of root.children) {
      const n = c as unknown as { tag?: string; props?: { style?: Record<string, Json> } };
      if (n && n.tag === "div") expect(n.props?.style?.willChange).toBe("transform");
    }
  });
});
