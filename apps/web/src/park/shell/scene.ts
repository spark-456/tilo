// The city scene behind every page (README "City backdrop": a 1600x1000 scene, drawn once and cached per
// `time|motion`; reference `Tilo App.dc.html` `renderVals`: still = motion is still, k = 1.9 when calm). The
// cars and walkers run on their own (CSS keyframes, engine/park.ts); a still scene freezes them. The cache lives
// at module level, not in a component, because a scene is expensive and the document needs one per key no
// matter how often the shell mounts.
import type { ReactNode } from "react";
import { type Pin, SCENE_H, SCENE_W } from "../app/pins";
import type { Spot } from "../engines/types";
import type { CityMotion } from "./cityMotion";
import { parkKit } from "./kit";

export interface BackdropScene {
  el: ReactNode;
  /** The three map pins on the 1600x1000 scene (not yet scaled to the window). */
  pins: Pin[];
}

/** Where the Home map pins want to sit and the smallest free spot each will take (reference `near`). */
const PIN_TARGETS: readonly (readonly [x: number, y: number, minArea: number])[] = [
  [1000, 420, 4],
  [820, 640, 4],
  [900, 250, 2],
];

/** Each target takes the nearest unused free spot of at least its area, else stays where it is. */
export function pickPins(spots: readonly Spot[]): Pin[] {
  const used = new Set<number>();
  return PIN_TARGETS.map(([tx, ty, min]) => {
    let best = -1;
    let bestDistance = Number.POSITIVE_INFINITY;
    spots.forEach((p, i) => {
      if (used.has(i) || p.area < min) return;
      const d = Math.hypot(p.x - tx, p.y - ty);
      if (d < bestDistance) {
        bestDistance = d;
        best = i;
      }
    });
    const spot = spots[best];
    if (!spot) return { x: tx, y: ty };
    used.add(best);
    return { x: spot.x, y: spot.y };
  });
}

const cache = new Map<string, BackdropScene>();

const keyOf = (time: "day" | "night", motion: CityMotion): string => `${time}|${motion}`;
const sceneOptions = (time: "day" | "night", motion: CityMotion) => ({
  w: SCENE_W,
  h: SCENE_H,
  vw: 1240,
  night: time === "night",
  k: motion === "calm" ? 1.9 : 1,
  still: motion === "still",
});
const finish = (drawn: { el: unknown; spots: readonly Spot[] }): BackdropScene => ({
  el: drawn.el as ReactNode,
  pins: pickPins(drawn.spots),
});

export function backdropScene(time: "day" | "night", motion: CityMotion): BackdropScene {
  const key = keyOf(time, motion);
  const hit = cache.get(key);
  if (hit) return hit;
  const scene = finish(parkKit().TP.scene(sceneOptions(time, motion)));
  cache.set(key, scene);
  return scene;
}

/** True when the scene for this key is already drawn and cached (reading it costs nothing). */
export const isDrawn = (time: "day" | "night", motion: CityMotion): boolean =>
  cache.has(keyOf(time, motion));

/**
 * The same scene, drawn in steps so no single task is long (NFR-01): call `next()` until it reports done; the
 * scene is then in the cache, where `backdropScene` finds it. The scene is identical to the one-go build.
 */
export function backdropSceneSteps(
  time: "day" | "night",
  motion: CityMotion,
): Generator<void, void, void> {
  return (function* () {
    const key = keyOf(time, motion);
    if (cache.has(key)) return;
    const drawn = yield* parkKit().TP.scene.steps(sceneOptions(time, motion));
    cache.set(key, finish(drawn));
  })();
}
