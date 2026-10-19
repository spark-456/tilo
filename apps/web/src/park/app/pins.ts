// Map pins (README "The `app` prop": `pins`). The city backdrop reports where three pins fit on the 1600x1000
// scene (shell/scene.ts); this turns those points into window coordinates for the current size, the way
// the reference does: x = (px - 800) * scale + vw / 2, y = (py - 500) * scale + vh / 2, with
// scale = max(vw / 1600, vh / 1000) (the same scale the scene is drawn at).
export interface Pin {
  x: number;
  y: number;
}

export const SCENE_W = 1600;
export const SCENE_H = 1000;

/** How much the scene is scaled to cover a window of this size. */
export const sceneScale = (vw: number, vh: number): number => Math.max(vw / SCENE_W, vh / SCENE_H);

export function screenPins(raw: readonly Pin[], vw: number, vh: number): Pin[] {
  const scale = sceneScale(vw, vh);
  return raw.map((p) => ({
    x: (p.x - SCENE_W / 2) * scale + vw / 2,
    y: (p.y - SCENE_H / 2) * scale + vh / 2,
  }));
}
