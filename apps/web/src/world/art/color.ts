// Colour helpers and the neutral world palette. Ported from design/source/tilo-world.js (the
// hx/mix/lt/dk helpers and the K0 ground tones, ADR-0003). Every colour here is a design token or
// a mix of tokens with black or white: the prototype's own ground and plinth hexes are not tokens,
// so they are derived from `surface` and `ink` rather than copied.
import tokens from "../../design/tokens";

const hx = (c: string): number[] => [1, 3, 5].map((i) => Number.parseInt(c.slice(i, i + 2), 16));
const toHex = (a: number[]): string =>
  `#${a
    .map((v) =>
      Math.max(0, Math.min(255, Math.round(v)))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;

export const mix = (a: string, b: string, t: number): string => {
  const [A, B] = [hx(a), hx(b)];
  return toHex(A.map((v, i) => v + ((B[i] ?? v) - v) * t));
};
export const lt = (c: string, t = 0.5): string => mix(c, "#ffffff", t);
export const dk = (c: string, t = 0.2): string => mix(c, "#000000", t);
/** Desaturates (archived buildings), as the prototype's `gray`. */
export const gray = (c: string): string => {
  const [r = 0, g = 0, b = 0] = hx(c);
  const y = 0.3 * r + 0.59 * g + 0.11 * b;
  return toHex([y, y, y]);
};
/** FNV-1a: a stable number from an id, for choices that must not change between frames. */
export function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export interface Shade {
  readonly t: string;
  readonly l: string;
  readonly r: string;
}
/** Top, left and right faces of a lit box from one base colour. */
export const shade = (c: string): Shade => ({ t: lt(c, 0.22), l: c, r: dk(c, 0.2) });

const { surface, ink, fog } = tokens.color;
export const PALETTE = {
  slab: {
    t: mix(surface["2"], surface["0"], 0.35),
    l: dk(surface["2"], 0.1),
    r: dk(surface["2"], 0.2),
  },
  road: dk(surface["2"], 0.05),
  plinth: { t: surface["1"], l: dk(surface["2"], 0.06), r: dk(surface["2"], 0.14) },
  pillLine: dk(surface["2"], 0.04),
  white: surface["1"],
  ink: ink["1"],
  ink2: ink["2"],
  scaffold: ink["3"],
  fog,
} as const;
