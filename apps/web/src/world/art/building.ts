// A building in one of its states, drawn from the solver's footprint. Ported from
// design/source/tilo-world.js (colorsFor, facade, roofEl, ghost, building; ADR-0003) with these
// changes: cells are the solver's grid units, the projection is tokens.stage's 2:1, and the
// prototype's blade-sign icons and animation are left out (the choreographer owns all motion).
// State is shown by shape as well as colour:
//   planned      dashed ghost outline, no walls        constructing  low walls, scaffold, ghost top
//   operational  full building, windows lit            completed     as operational
//   archived     the same building in greys
import type { Graphics } from "pixi.js";
import { PALETTE, dk, gray, lt } from "./color";
import { P, type Proj, type Pt, box, dashed, poly, stroke } from "./iso";

export type Roof = "flat" | "gable" | "dome";
export type Facade = "windows" | "band" | "arches";
export type BuildingShown = "planned" | "constructing" | "operational" | "completed" | "archived";

export interface BuildingArt {
  readonly x: number; // footprint in grid cells
  readonly y: number;
  readonly w: number;
  readonly d: number;
  readonly floors: number;
  readonly status: BuildingShown;
  readonly tint: string;
  readonly roof: Roof;
  readonly facade: Facade;
  readonly lift: number; // px: the level this building stands on
}

const INS = 0.1; // cells of margin round the footprint
const PLINTH = 3;
export const BASE = 26; // wall height of a one-floor building, px
export const FLOOR = 20; // each further floor, px
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

function colours(tint: string) {
  const wl = lt(tint, 0.8);
  return {
    wl,
    wr: dk(wl, 0.15),
    wt: lt(wl, 0.35),
    roof: tint,
    roofB: lt(tint, 0.14),
    roofR: dk(tint, 0.24),
    roofT: lt(tint, 0.22),
    door: dk(tint, 0.45),
    win: lt(tint, 0.45),
  };
}
type Colours = ReturnType<typeof colours>;

/** Three dashed faces over a pale fill: a building that is planned, or the part not yet built. */
function ghost(
  g: Graphics,
  p: Proj,
  x: number,
  y: number,
  z: number,
  W: number,
  D: number,
  H: number,
) {
  const faces: Pt[][] = [
    [p(x, y + D, z), p(x + W, y + D, z), p(x + W, y + D, z + H), p(x, y + D, z + H)],
    [p(x + W, y + D, z), p(x + W, y, z), p(x + W, y, z + H), p(x + W, y + D, z + H)],
    [p(x, y, z + H), p(x + W, y, z + H), p(x + W, y + D, z + H), p(x, y + D, z + H)],
  ];
  for (const f of faces) poly(g, f, PALETTE.white, 0.5);
  for (const f of faces) dashed(g, f, { color: PALETTE.ink2 });
}

/** Windows, floor lines and the door on one wall ("L" faces the viewer's left, "R" the right). */
function facade(
  g: Graphics,
  p: Proj,
  side: "L" | "R",
  at: { x: number; y: number; W: number; D: number },
  hb: number,
  floors: number,
  c: Colours,
  kind: Facade,
  lit: boolean,
) {
  const { x, y, W, D } = at;
  const len = side === "L" ? W : D;
  const pt = (u: number, v: number): Pt =>
    side === "L" ? p(x + u * W, y + D, PLINTH + v) : p(x + W, y + D - u * D, PLINTH + v);
  const quad = (u0: number, u1: number, v0: number, v1: number, col: string) =>
    poly(g, [pt(u0, v0), pt(u1, v0), pt(u1, v1), pt(u0, v1)], col);
  const base = side === "L" ? c.wl : c.wr;
  for (let i = 1; i < floors; i++)
    quad(0, 1, BASE + (i - 1) * FLOOR - 2, BASE + (i - 1) * FLOOR + 0.5, dk(base, 0.07));
  const n = Math.max(1, Math.floor(len * 1.6));
  const door = side === "L" ? 0.28 : -1;
  for (let f = 0; f < floors; f++) {
    const v0 = f === 0 ? 8 : BASE + (f - 1) * FLOOR + 5;
    const win = lit ? PALETTE.white : c.win;
    if (kind === "band") {
      quad(f === 0 && side === "L" ? 0.42 : 0.08, 0.92, v0, v0 + 9, win);
      continue;
    }
    for (let i = 0; i < n; i++) {
      const u = (i + 0.5) / n;
      if (f === 0 && Math.abs(u - door) < 0.13) continue;
      const hw = (kind === "arches" ? 0.2 : 0.24) / n;
      if (kind === "arches") {
        const cut = 3;
        poly(
          g,
          [
            pt(u - hw, v0),
            pt(u + hw, v0),
            pt(u + hw, v0 + 11 - cut),
            pt(u + hw * 0.5, v0 + 12),
            pt(u - hw * 0.5, v0 + 12),
            pt(u - hw, v0 + 11 - cut),
          ],
          win,
        );
      } else quad(u - hw, u + hw, v0, v0 + 11, win);
    }
  }
  if (side === "L") quad(door - 0.07, door + 0.07, 0, 15, c.door);
}

function roofOf(
  g: Graphics,
  p: Proj,
  kind: Roof,
  a: { x: number; y: number; W: number; D: number; z: number },
  c: Colours,
): number {
  const { x, y, W, D, z } = a;
  if (kind === "flat") {
    box(g, p, [x - 0.05, y - 0.05, z], [W + 0.1, D + 0.1, 5], {
      t: c.roofT,
      l: c.roof,
      r: c.roofR,
    });
    poly(
      g,
      [
        p(x + 0.12, y + 0.12, z + 5),
        p(x + W - 0.12, y + 0.12, z + 5),
        p(x + W - 0.12, y + D - 0.12, z + 5),
        p(x + 0.12, y + D - 0.12, z + 5),
      ],
      dk(c.roofT, 0.1),
    );
    return 5;
  }
  if (kind === "gable") {
    const rh = clamp(Math.min(W, D) * 18, 12, 26);
    const o = 0.08;
    if (W >= D) {
      const ym = y + D / 2;
      poly(
        g,
        [
          p(x - o, y - o, z - 2),
          p(x + W + o, y - o, z - 2),
          p(x + W + o, ym, z + rh),
          p(x - o, ym, z + rh),
        ],
        c.roofB,
      );
      poly(g, [p(x + W, y, z), p(x + W, y + D, z), p(x + W, ym, z + rh)], c.wr);
      poly(
        g,
        [
          p(x - o, y + D + o, z - 2),
          p(x + W + o, y + D + o, z - 2),
          p(x + W + o, y + D + o, z - 5),
          p(x - o, y + D + o, z - 5),
        ],
        dk(c.roof, 0.32),
      );
      poly(
        g,
        [
          p(x - o, y + D + o, z - 2),
          p(x + W + o, y + D + o, z - 2),
          p(x + W + o, ym, z + rh),
          p(x - o, ym, z + rh),
        ],
        c.roof,
      );
      stroke(g, [p(x - o, ym, z + rh), p(x + W + o, ym, z + rh)], dk(c.roof, 0.3), 2.2);
    } else {
      const xm = x + W / 2;
      poly(
        g,
        [
          p(x - o, y - o, z - 2),
          p(x - o, y + D + o, z - 2),
          p(xm, y + D + o, z + rh),
          p(xm, y - o, z + rh),
        ],
        c.roofB,
      );
      poly(g, [p(x, y + D, z), p(x + W, y + D, z), p(xm, y + D, z + rh)], c.wl);
      poly(
        g,
        [
          p(x + W + o, y - o, z - 2),
          p(x + W + o, y + D + o, z - 2),
          p(x + W + o, y + D + o, z - 5),
          p(x + W + o, y - o, z - 5),
        ],
        dk(c.roof, 0.45),
      );
      poly(
        g,
        [
          p(x + W + o, y - o, z - 2),
          p(x + W + o, y + D + o, z - 2),
          p(xm, y + D + o, z + rh),
          p(xm, y - o, z + rh),
        ],
        c.roofR,
      );
      stroke(g, [p(xm, y - o, z + rh), p(xm, y + D + o, z + rh)], dk(c.roof, 0.35), 2.2);
    }
    return rh;
  }
  // dome: two quarter-ellipse halves over a low drum
  box(g, p, [x + 0.04, y + 0.04, z], [W - 0.08, D - 0.08, 4], {
    t: c.roofT,
    l: c.roofR,
    r: dk(c.roofR, 0.15),
  });
  const [cx, cy] = p(x + W / 2, y + D / 2, z + 4);
  const R = Math.min(W, D) * 22;
  const ry = R * 0.5;
  const arc = (sign: 1 | -1): Pt[] =>
    Array.from({ length: 17 }, (_, i) => {
      const a = (i / 16) * Math.PI;
      return i <= 8
        ? ([cx + sign * R * Math.sin(a), cy - R * Math.cos(a)] as Pt)
        : ([cx + sign * R * Math.sin(a), cy - ry * Math.cos(a)] as Pt);
    });
  poly(g, arc(-1), c.roof);
  poly(g, arc(1), c.roofR);
  g.circle(cx, cy - R - 2, 2.6).fill({ color: dk(c.roof, 0.3) });
  return 4 + R;
}

/** Draws one building into `g` (which the caller has cleared) and returns the point above its roof
 * where the state pin and name label hang. */
export function drawBuilding(g: Graphics, b: BuildingArt): Pt {
  const p: Proj = (x, y, z = 0) => P(x, y, z + b.lift);
  const [x, y] = [b.x + INS, b.y + INS];
  const [W, D] = [b.w - 2 * INS, b.d - 2 * INS];
  const H = BASE + (b.floors - 1) * FLOOR;
  if (b.status === "planned") {
    ghost(g, p, x, y, PLINTH, W, D, H);
    return p(x + W / 2, y + D / 2, PLINTH + H);
  }
  const c = colours(b.status === "archived" ? gray(lt(b.tint, 0.2)) : b.tint);
  const cons = b.status === "constructing";
  const hb = cons ? Math.max(24, Math.round(H * 0.45)) : H;
  const floors = cons ? 1 : b.floors;
  const lit = b.status === "operational" || b.status === "completed";
  box(g, p, [x - 0.08, y - 0.08, 0], [W + 0.16, D + 0.16, PLINTH], PALETTE.plinth);
  box(g, p, [x, y, PLINTH], [W, D, hb], { t: c.wt, l: c.wl, r: c.wr });
  facade(g, p, "L", { x, y, W, D }, hb, floors, c, b.facade, lit);
  facade(g, p, "R", { x, y, W, D }, hb, floors, c, b.facade, lit);
  let roofH = 0;
  if (cons) {
    ghost(g, p, x, y, PLINTH + hb, W, D, H - hb);
    const post = [
      [x - 0.06, y + D + 0.06],
      [x + W + 0.06, y + D + 0.06],
      [x + W + 0.06, y - 0.06],
      [x + W / 2, y + D + 0.06],
    ] as const;
    for (const [a, q] of post)
      stroke(g, [p(a, q, PLINTH), p(a, q, PLINTH + H)], PALETTE.scaffold, 2.2);
    for (let z = 16; z <= H; z += 16) {
      stroke(
        g,
        [
          p(x - 0.06, y + D + 0.06, PLINTH + z),
          p(x + W + 0.06, y + D + 0.06, PLINTH + z),
          p(x + W + 0.06, y - 0.06, PLINTH + z),
        ],
        PALETTE.scaffold,
        2.2,
      );
    }
  } else {
    roofH = roofOf(g, p, b.roof, { x, y, W, D, z: PLINTH + H }, c);
  }
  return p(x + W / 2, y + D / 2, PLINTH + H + roofH + 2);
}
