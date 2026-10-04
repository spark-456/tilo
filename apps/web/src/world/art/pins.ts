// Billboard pins that state a thing's condition above it. Ported from design/source/tilo-world.js
// (pin, ADR-0003) without the icon set: each kind has its own glyph SHAPE (tick, dot, lock, flag,
// diamond, seal), so a state never rests on colour alone. Colours are token roles.
import type { Graphics } from "pixi.js";
import tokens from "../../design/tokens";
import { PALETTE, dk } from "./color";
import { type Pt, stroke } from "./iso";

const { signal, brand } = tokens.color;
// `policy` has no value in the exports (tokens.json: status missing): the neutral fallback, which
// is also what the HR-7 stamp uses. The seal shape and the "Policy" tag carry the meaning.
const POLICY = tokens.color.policy;

export type PinKind = "active" | "complete" | "skipped" | "lock" | "needs" | "blocked" | "policy";

/** Draws a pin whose pole stands at `at`; `tint` colours the "active" ring. */
export function drawPin(
  g: Graphics,
  at: Pt,
  kind: PinKind,
  opts: { lift?: number; r?: number; tint?: string } = {},
): void {
  const { lift = 26, r = 11, tint = brand.primary } = opts;
  const [x, y] = at;
  const cy = y - lift;
  stroke(g, [at, [x, cy + r]], PALETTE.ink, 2);
  const white = { width: 2.5, color: PALETTE.white };
  const glyph = (pts: Pt[], color: string, w = 2.6) => stroke(g, pts, color, w);
  if (kind === "blocked") {
    g.poly([x, cy - r, x + r, cy, x, cy + r, x - r, cy])
      .fill({ color: signal.blocked })
      .stroke(white);
    glyph(
      [
        [x, cy - 4],
        [x, cy + 1],
      ],
      PALETTE.white,
    );
    g.circle(x, cy + 4.4, 1.5).fill({ color: PALETTE.white });
    return;
  }
  if (kind === "policy") {
    // A seal: an octagon, the "stamp" of HR-7, with a tick.
    const pts = Array.from({ length: 8 }, (_, i) => [
      x + r * Math.cos((i + 0.5) * (Math.PI / 4)),
      cy + r * Math.sin((i + 0.5) * (Math.PI / 4)),
    ]);
    g.poly(pts.flat()).fill({ color: POLICY }).stroke(white);
    glyph(
      [
        [x - 4, cy],
        [x - 1, cy + 3],
        [x + 4, cy - 3],
      ],
      PALETTE.white,
      2.4,
    );
    return;
  }
  const fill =
    kind === "active"
      ? PALETTE.white
      : kind === "complete"
        ? signal.done
        : kind === "needs"
          ? signal.needs
          : tokens.color.ink["3"];
  g.circle(x, cy, r)
    .fill({ color: fill })
    .stroke(kind === "active" ? { width: 2.5, color: tint } : white);
  if (kind === "active") g.circle(x, cy, 3.4).fill({ color: dk(tint, 0.15) });
  else if (kind === "complete")
    glyph(
      [
        [x - 5, cy + 0.5],
        [x - 1.5, cy + 4],
        [x + 5.5, cy - 3.5],
      ],
      PALETTE.white,
      3,
    );
  else if (kind === "needs")
    glyph(
      [
        [x - 4, cy + 6],
        [x - 4, cy - 6],
        [x + 4, cy - 3],
        [x - 4, cy],
      ],
      PALETTE.ink,
      2.2,
    );
  else if (kind === "lock") {
    g.roundRect(x - 5, cy - 1, 10, 7, 2).fill({ color: PALETTE.white });
    glyph(
      [
        [x - 3, cy - 1],
        [x - 3, cy - 4],
        [x + 3, cy - 4],
        [x + 3, cy - 1],
      ],
      PALETTE.white,
      1.8,
    );
  } else g.circle(x, cy, 3.4).fill({ color: PALETTE.white });
}
