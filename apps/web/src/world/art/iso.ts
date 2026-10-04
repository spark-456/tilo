// Isometric drawing primitives for the Pixi world. Ported from design/source/tilo-world.js
// (P, poly, box, ghost outlines, ADR-0003): SVG polygons became Graphics paths, and the prototype's
// own 0.866/0.5 projection became the 2:1 projection of tokens.stage, so footprints from the
// solver (grid units) land exactly on the iso grid Stage.tsx draws.
import type { Graphics } from "pixi.js";
import tokens from "../../design/tokens";
import type { Shade } from "./color";

const { tileWidth: TW, tileHeight: TH } = tokens.stage;

export type Pt = readonly [number, number];
/** Grid point (x, y in cells) at height z (px) to world px. */
export type Proj = (x: number, y: number, z?: number) => Pt;

export const P: Proj = (x, y, z = 0) => [((x - y) * TW) / 2, ((x + y) * TH) / 2 - z];

const flat = (pts: readonly Pt[]): number[] => pts.flatMap((p) => [p[0], p[1]]);

/** A filled polygon; the same-colour hairline stroke closes the seams between faces. */
export function poly(g: Graphics, pts: readonly Pt[], color: string, alpha = 1): void {
  g.poly(flat(pts)).fill({ color, alpha }).stroke({ width: 0.7, color, alpha, join: "round" });
}

/** An extruded box: left face (towards the viewer), right face, top (p: the projection). */
export function box(
  g: Graphics,
  p: Proj,
  [x, y, z]: readonly [number, number, number],
  [w, d, h]: readonly [number, number, number],
  c: Shade,
): void {
  poly(g, [p(x, y + d, z), p(x + w, y + d, z), p(x + w, y + d, z + h), p(x, y + d, z + h)], c.l);
  poly(g, [p(x + w, y + d, z), p(x + w, y, z), p(x + w, y, z + h), p(x + w, y + d, z + h)], c.r);
  poly(g, [p(x, y, z + h), p(x + w, y, z + h), p(x + w, y + d, z + h), p(x, y + d, z + h)], c.t);
}

/** A dashed outline: how a planned building (a plan, not yet built) and a connection still being
 * made are drawn, so the state reads from the shape and not from colour alone. */
export function dashed(
  g: Graphics,
  pts: readonly Pt[],
  opts: { color: string; width?: number; dash?: number; gap?: number; closed?: boolean },
): void {
  const { color, width = 1.5, dash = 5, gap = 4, closed = true } = opts;
  const loop = closed ? [...pts, pts[0] as Pt] : pts;
  let on = true;
  let left = dash;
  for (let i = 1; i < loop.length; i++) {
    const [a, b] = [loop[i - 1] as Pt, loop[i] as Pt];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    let at = 0;
    while (at < len) {
      const step = Math.min(left, len - at);
      const [f, t] = [at / len, (at + step) / len];
      if (on) {
        g.moveTo(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f);
        g.lineTo(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t);
      }
      at += step;
      left -= step;
      if (left <= 0) {
        on = !on;
        left = on ? dash : gap;
      }
    }
  }
  g.stroke({ width, color, cap: "round", join: "round" });
}

/** A solid polyline stroke. */
export function stroke(g: Graphics, pts: readonly Pt[], color: string, width: number): void {
  const [first, ...rest] = pts;
  if (!first) return;
  g.moveTo(first[0], first[1]);
  for (const q of rest) g.lineTo(q[0], q[1]);
  g.stroke({ width, color, cap: "round", join: "round" });
}

/** The diamond a grid rect covers on the ground at height z. */
export const ground = (r: { x: number; y: number; w: number; d: number }, z = 0): Pt[] => [
  P(r.x, r.y, z),
  P(r.x + r.w, r.y, z),
  P(r.x + r.w, r.y + r.d, z),
  P(r.x, r.y + r.d, z),
];
