// The city scene behind every page (README "City backdrop": a 1600x1000 scene, drawn once and cached per
// `time|motion`; reference `Tilo App.dc.html` `renderVals`). The scene is STATIC here: no cars or walkers
// move (the motion restore is BQ-WEB-3). The cache lives at module level, not in a component, because a
// scene is expensive and the document needs one per key no matter how often the shell mounts.
import type { ReactNode } from "react";
import { type Pin, SCENE_H, SCENE_W } from "../app/pins";
import type { Spot } from "../engines/types";
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

export function backdropScene(time: "day" | "night", motion: string): BackdropScene {
  const key = `${time}|${motion}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const night = time === "night";
  const drawn = parkKit().TP.scene({
    w: SCENE_W,
    h: SCENE_H,
    vw: 1240,
    night,
    k: motion === "calm" ? 1.9 : 1,
    still: true,
  });
  const scene = { el: drawn.el as ReactNode, pins: pickPins(drawn.spots) };
  cache.set(key, scene);
  return scene;
}
