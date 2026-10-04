// Ground-level drawing: level plates, district plots, roads, bridges, island slabs with cloud
// cover, gates and trees. Ported from design/source/tilo-world.js (ground slabs, road strips,
// clouds, gate, tree; ADR-0003). The prototype laid these out itself; here every position comes
// from the solver's geometry, and the colours from tokens (district tint roles, fog, signal).
import type { Graphics } from "pixi.js";
import tokens from "../../design/tokens";
import { PALETTE, dk, hash, lt, shade } from "./color";
import { P, type Pt, box, dashed, ground, poly } from "./iso";

export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly d: number;
}
export type Bridge = "road" | "rail" | "footpath" | "pier";
export type Link = "locked" | "requested" | "connected" | "failed";
export type GateLook = "closed" | "waiting" | "open" | "policy";

export const LEVEL_RISE = 110; // px between stacked level plates
const SLAB = 14; // thickness of a plate, px
export const MARGIN = 0.9; // cells of ground round a plate, where the trees stand

export function drawPlate(g: Graphics, r: Rect, lift: number): void {
  const m = MARGIN;
  box(g, P, [r.x - m, r.y - m, lift - SLAB], [r.w + 2 * m, r.d + 2 * m, SLAB], PALETTE.slab);
}

export function drawDistrict(g: Graphics, r: Rect, tint: string, lift: number): void {
  box(g, P, [r.x, r.y, lift], [r.w, r.d, 3], {
    t: lt(tint, 0.68),
    l: lt(tint, 0.42),
    r: lt(tint, 0.3),
  });
  const i = 0.2;
  poly(
    g,
    ground({ x: r.x + i, y: r.y + i, w: r.w - 2 * i, d: r.d - 2 * i }, lift + 3.1),
    lt(tint, 0.8),
  );
}

/** A strip of the given width (cells) along a polyline of grid points, with square joints. */
function strip(
  g: Graphics,
  pts: readonly { x: number; y: number }[],
  width: number,
  color: string,
  lift: number,
): void {
  const h = width / 2;
  const at = (x: number, y: number): Pt => P(x, y, lift + 0.2);
  for (let i = 1; i < pts.length; i++) {
    const [a, b] = [pts[i - 1], pts[i]] as [{ x: number; y: number }, { x: number; y: number }];
    const len = Math.hypot(b.x - a.x, b.y - a.y) || 1;
    const [nx, ny] = [(-(b.y - a.y) / len) * h, ((b.x - a.x) / len) * h];
    poly(
      g,
      [
        at(a.x + nx, a.y + ny),
        at(b.x + nx, b.y + ny),
        at(b.x - nx, b.y - ny),
        at(a.x - nx, a.y - ny),
      ],
      color,
    );
  }
  for (const q of pts)
    poly(
      g,
      [at(q.x - h, q.y - h), at(q.x + h, q.y - h), at(q.x + h, q.y + h), at(q.x - h, q.y + h)],
      color,
    );
}

export function drawRoad(
  g: Graphics,
  path: readonly { x: number; y: number }[],
  lift: number,
): void {
  strip(g, path, 0.6, PALETTE.road, lift);
}

const BRIDGE_WIDTH: Readonly<Record<Bridge, number>> = {
  road: 0.6,
  pier: 0.6,
  rail: 0.4,
  footpath: 0.3,
};

/** A connected bridge is a solid strip; one that is not (yet or any more) is drawn as a dashed
 * outline of the same strip, so "under construction" reads from shape, not colour. */
export function drawBridge(
  g: Graphics,
  path: readonly { x: number; y: number }[],
  kind: Bridge,
  state: Link,
  lift: number,
): void {
  const color = dk(PALETTE.road, kind === "road" ? 0.1 : 0.22);
  if (state === "connected") {
    strip(g, path, BRIDGE_WIDTH[kind], color, lift);
    return;
  }
  const edge = state === "failed" ? tokens.color.signal.blocked : PALETTE.ink2;
  const h = BRIDGE_WIDTH[kind] / 2;
  const [first, last] = [path[0], path[path.length - 1]];
  if (!first || !last) return;
  // The strip's two long edges, as dashed lines along the same polyline.
  for (const s of [-1, 1]) {
    const side = path.map((q, i) => {
      const o = path[Math.min(i + 1, path.length - 1)] ?? q;
      const p0 = path[Math.max(i - 1, 0)] ?? q;
      const len = Math.hypot(o.x - p0.x, o.y - p0.y) || 1;
      return P(q.x + (s * h * -(o.y - p0.y)) / len, q.y + (s * h * (o.x - p0.x)) / len, lift + 0.2);
    });
    dashed(g, side, { color: edge, width: 1.6, closed: false });
  }
}

/** An island: a slab on the plate, under cloud cover while locked (no access yet). */
export function drawIsland(g: Graphics, r: Rect, state: Link, id: string, lift: number): void {
  box(g, P, [r.x, r.y, lift], [r.w, r.d, 6], PALETTE.slab);
  poly(
    g,
    ground({ x: r.x + 0.2, y: r.y + 0.2, w: r.w - 0.4, d: r.d - 0.4 }, lift + 6.1),
    PALETTE.plinth.t,
  );
  if (state !== "locked") return;
  // Cloud puffs, placed from the island id so they never change between frames.
  let seed = hash(id);
  const rnd = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  const [nx, ny] = [Math.max(2, Math.round(r.w * 1.3)), Math.max(2, Math.round(r.d * 1.3))];
  const puffs: { at: Pt; r: number; k: number }[] = [];
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const gx = r.x + (r.w * (i + 0.5)) / nx + (rnd() - 0.5) * 0.3;
      const gy = r.y + (r.d * (j + 0.5)) / ny + (rnd() - 0.5) * 0.3;
      puffs.push({ at: P(gx, gy, lift + 36 + rnd() * 10), r: 19 + rnd() * 8, k: gx + gy });
    }
  }
  for (const c of puffs.sort((a, b) => a.k - b.k)) {
    g.circle(c.at[0], c.at[1] + 4, c.r).fill({ color: PALETTE.fog });
    g.circle(c.at[0], c.at[1], c.r).fill({ color: PALETTE.white });
  }
}

const GATE_COLOUR: Readonly<Record<GateLook, string>> = {
  closed: tokens.color.ink["3"],
  waiting: tokens.color.signal.needs,
  open: tokens.color.signal.done,
  policy: tokens.color.policy,
};

/** A gate across a road cell. Shut or waiting: a barrier across the road. Open (a person or a
 * policy opened it): the barrier is lifted into a lintel. The posts are always there. */
export function drawGate(
  g: Graphics,
  cell: { x: number; y: number },
  state: GateLook,
  lift: number,
): void {
  const col = GATE_COLOUR[state];
  const post = { t: lt(PALETTE.ink2, 0.5), l: lt(PALETTE.ink2, 0.25), r: PALETTE.ink2 };
  const [x, y] = [cell.x, cell.y + 0.45];
  box(g, P, [x + 0.05, y, lift], [0.12, 0.12, 22], post);
  box(g, P, [x + 0.83, y, lift], [0.12, 0.12, 22], post);
  const raised = state === "open" || state === "policy";
  box(g, P, [x + 0.12, y + 0.02, lift + (raised ? 20 : 6)], [0.78, 0.08, raised ? 3 : 9], {
    t: PALETTE.white,
    l: PALETTE.white,
    r: lt(col, 0.4),
  });
  if (!raised)
    dashed(
      g,
      [
        P(x + 0.12, y + 0.1, lift + 6),
        P(x + 0.9, y + 0.1, lift + 6),
        P(x + 0.9, y + 0.1, lift + 15),
        P(x + 0.12, y + 0.1, lift + 15),
      ],
      { color: col, width: 1.4 },
    );
}

/** A tree: trunk, then a round crown or a pine, from the same tokens as the prototype's. */
export function drawTree(g: Graphics, gx: number, gy: number, size: number, pine: boolean): void {
  const crown = lt(tokens.color.district.accounts, 0.45);
  const [px, py] = P(gx, gy);
  box(g, P, [gx - 0.05, gy - 0.05, 0], [0.1, 0.1, 6], shade(dk(PALETTE.scaffold, 0.2)));
  if (pine) {
    const w = size * 1.25;
    g.poly([px - w, py - 5, px, py - 5 - size * 2.7, px, py - 5 + w * 0.42]).fill({ color: crown });
    g.poly([px + w, py - 5, px, py - 5 - size * 2.7, px, py - 5 + w * 0.42]).fill({
      color: dk(crown, 0.18),
    });
  } else {
    // A round crown as two half discs (lit left, shaded right), as polygons: an arc path would
    // be joined to wherever the last path ended.
    const [cy, r] = [py - 6 - size, size * 1.22];
    const half = (side: 1 | -1) =>
      Array.from({ length: 13 }, (_, i) => {
        const a = -Math.PI / 2 + (i / 12) * Math.PI;
        return [px + side * r * Math.cos(a), cy + r * Math.sin(a)];
      }).flat();
    g.poly(half(-1)).fill({ color: crown });
    g.poly(half(1)).fill({ color: dk(crown, 0.18) });
  }
}
