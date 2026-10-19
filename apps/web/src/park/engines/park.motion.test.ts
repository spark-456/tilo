// WEB-MOTION-1 (design_handoff_tilo_web_app README "City backdrop", "Performance"; Tilo App.dc.html and
// tilo-park.js keyframes mvXY, waddle): the live city. With `still: false` the engine draws its cars and
// walkers exactly as the handoff prototype does (the same mover layers, the same durations, phases and travel,
// seeded from the same rng) and `k` slows them (README: calm is slower, the prototype passes k = 1.9). With
// `still: true` nothing carries an animation and every mover sits at its seeded phase.
// The prototype runs in a Node vm (test-support/park/engineProto.ts); the port must carry the same movers.
// What this does NOT pin: how a walker flips its two frames (the prototype animates background-position with
// `sprite2`; the binding performance budget allows only transform and opacity, so that is the builder's
// call and is checked in the browser by e2e/park-motion-backdrop.spec.ts).
import * as fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  type Engine,
  type Json,
  type TestH,
  call,
  canon,
  fakeEnv,
  protoPark,
  serialiseH,
} from "../../../test-support/park/engineProto";
import { createPark } from "./park";
import { createWorld } from "./world";

const SLOW = { timeout: 180_000 };

type MakePark = (h: TestH, makeWorld: typeof createWorld, env?: unknown) => Engine;
const portPark = (): Engine =>
  (createPark as unknown as MakePark)(serialiseH, createWorld, fakeEnv);

type Node = { tag: string; props: Record<string, Json> | null; children: Json[] };

/** Every element node of a canonical tree. */
function nodes(j: Json): Node[] {
  const out: Node[] = [];
  const walk = (x: Json): void => {
    if (Array.isArray(x)) {
      x.forEach(walk);
      return;
    }
    if (x && typeof x === "object") {
      if ("tag" in x && "props" in x && "children" in x) out.push(x as unknown as Node);
      for (const v of Object.values(x)) walk(v as Json);
    }
  };
  walk(j);
  return out;
}
const styleOf = (n: Node): Record<string, Json> =>
  ((n.props?.style as Record<string, Json> | undefined) ?? {}) as Record<string, Json>;

/** The animation shorthand of every element that runs `name`, with its travel variables, sorted. */
function runs(tree: unknown, name: string): string[] {
  return nodes(canon(tree))
    .map(styleOf)
    .filter((s) => typeof s.animation === "string" && s.animation.startsWith(`${name} `))
    .map((s) => `${s.animation}|${String(s["--dx"])}|${String(s["--dy"])}`)
    .sort();
}
const sceneEl = (engine: Engine, opts: Record<string, unknown>): unknown =>
  (call(engine, "scene", opts) as { el: unknown }).el;

const BASE = { w: 1000, h: 700 };

describe("WEB-MOTION-1 engine: movers animate as the handoff draws them", () => {
  it(
    "WEB-MOTION-1 still false: every car runs mvXY with the prototype's duration, phase and travel",
    SLOW,
    () => {
      const proto = runs(sceneEl(protoPark(), { ...BASE, still: false }), "mvXY");
      expect(proto.length, "the prototype has moving cars and walkers").toBeGreaterThan(3);
      const port = runs(sceneEl(portPark(), { ...BASE, still: false }), "mvXY");
      expect(port).toEqual(proto);
    },
  );

  it(
    "WEB-MOTION-1 still false: every walker keeps the prototype's waddle (cycle, phase)",
    SLOW,
    () => {
      const proto = runs(sceneEl(protoPark(), { ...BASE, still: false }), "waddle");
      expect(proto.length, "the prototype has walkers").toBeGreaterThan(0);
      const port = runs(sceneEl(portPark(), { ...BASE, still: false }), "waddle");
      expect(port).toEqual(proto);
    },
  );

  it(
    "WEB-MOTION-1 calm: k = 1.9 stretches every mvXY duration the way the prototype does (slower, same places)",
    SLOW,
    () => {
      const lively = runs(sceneEl(portPark(), { ...BASE, still: false, k: 1 }), "mvXY");
      const calmProto = runs(sceneEl(protoPark(), { ...BASE, still: false, k: 1.9 }), "mvXY");
      const calmPort = runs(sceneEl(portPark(), { ...BASE, still: false, k: 1.9 }), "mvXY");
      expect(calmPort).toEqual(calmProto);
      expect(calmPort).not.toEqual(lively); // slower, not the same picture
      expect(calmPort).toHaveLength(lively.length); // the same movers, slower (README: calm = fewer/slower)
    },
  );

  it(
    "WEB-MOTION-1 property: for any k in [1, 3] the port's mover durations equal the prototype's",
    SLOW,
    () => {
      const small = { w: 600, h: 400, still: false };
      fc.assert(
        fc.property(fc.integer({ min: 10, max: 30 }), (tenths) => {
          const k = tenths / 10;
          const proto = runs(sceneEl(protoPark(), { ...small, k }), "mvXY");
          const port = runs(sceneEl(portPark(), { ...small, k }), "mvXY");
          expect(port).toEqual(proto);
        }),
        { numRuns: 5 },
      );
    },
  );

  it(
    "WEB-MOTION-1 still true: no element carries an animation and the movers sit at a fixed translate",
    SLOW,
    () => {
      const tree = nodes(canon(sceneEl(portPark(), { ...BASE, still: true })));
      const animated = tree.filter((n) => {
        const a = styleOf(n).animation;
        return typeof a === "string" && a !== "none";
      });
      expect(animated).toEqual([]);
      const movers = tree.filter((n) => styleOf(n).willChange === "transform");
      expect(movers.length).toBeGreaterThan(3);
      for (const m of movers) expect(String(styleOf(m).transform ?? "")).toMatch(/^translate\(/);
    },
  );

  it(
    "WEB-MOTION-1 honesty (HR-1, BQ-WEB-3): only the car and walker layers animate; buildings and their agents are static pictures",
    SLOW,
    () => {
      const tree = nodes(canon(sceneEl(portPark(), { ...BASE, still: false })));
      const animated = tree.filter((n) => {
        const a = styleOf(n).animation;
        return typeof a === "string" && a !== "none";
      });
      expect(animated.length).toBeGreaterThan(3);
      // A building, a tree or an agent standing at a building is drawn into an <img> (a blob SVG). An img
      // never carries an animation, and nothing inside the static art is a separate live layer.
      for (const n of tree.filter((x) => x.tag === "img")) {
        expect(styleOf(n).animation, "an image is static art").toBeUndefined();
      }
      // The cars and walkers are the only live layers (README "Performance"): one mover layer each.
      const moverCount = tree.filter((n) => styleOf(n).willChange === "transform").length;
      expect(moverCount).toBeGreaterThan(3);
    },
  );
});
