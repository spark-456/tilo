// THROWAWAY (WEB-3b validation only).
import type { Motion } from "../app/AppCtx";
import type { El, SceneOpts, Spot } from "../engines/types";

export type Scene = { el: El; spots: Spot[] };

export function createSceneCache(scene: (o?: SceneOpts) => Scene) {
  const cache = new Map<string, Scene>();
  return (time: "day" | "night", motion: Motion): Scene => {
    const key = `${time}|${motion}`;
    const hit = cache.get(key);
    if (hit) return hit;
    const built = scene({ w: 1600, h: 1000, vw: 1240, night: time === "night", still: true });
    cache.set(key, built);
    return built;
  };
}
