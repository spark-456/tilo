// An agent figure, drawn once with its feet at the origin. Ported from design/source/tilo-world.js
// (agent, ADR-0003): the same boxy rig and face, in a neutral expression. The prototype's walking
// bob, expressions and role props are not ported (all motion is the choreographer's, and the
// layout carries a rank, not a role). Rank is shown by SHAPE: a director wears a crest, a lead a
// cap, a verifier carries a clipboard, a specialist is plain; colour is only identity.
import type { Graphics } from "pixi.js";
import tokens from "../../design/tokens";
import { PALETTE, dk, lt, shade } from "./color";
import { type Proj, box, poly } from "./iso";

const PF: Proj = (x, y, z = 0) => [(x - y) * 0.95, (x + y) * 0.475 - z * 0.95];
const HEIGHT: Readonly<Record<string, number>> = {
  specialist: 15,
  verifier: 15,
  lead: 17,
  director: 19,
};

export const AGENT_SCALE = 1.35;

export function drawAgent(g: Graphics, rank: string, tint: string, shadows = true): void {
  const director = rank === "director";
  const col = director ? tokens.color.brand.primary : tint;
  const [cT, cR, limb] = [lt(col, 0.2), dk(col, 0.22), dk(col, 0.3)];
  const w = director ? 15 : 13;
  const hh = HEIGHT[rank] ?? 15;
  const [x0, y0, z] = [-w / 2, -w / 2, 3];
  if (shadows) g.ellipse(0, 0, w * 0.95, w * 0.5).fill({ color: PALETTE.ink, alpha: 0.13 });
  const leg = { t: limb, l: limb, r: dk(limb, 0.2) };
  box(g, PF, [x0 + 2, y0 + w - 5, 0], [4, 4, 3], leg);
  box(g, PF, [x0 + w - 6, y0 + w - 5, 0], [4, 4, 3], leg);
  box(g, PF, [x0 - 3, y0 + w - 4, z + 3], [3, 3.5, hh * 0.45], leg);
  box(g, PF, [x0 + w, y0 + w - 4, z + 3], [3, 3.5, hh * 0.45], leg);
  box(g, PF, [x0 + 1.2, y0 + 1.2, z + 1], [w - 2.4, w - 2.4, hh - 2], { t: cR, l: cR, r: cR });
  poly(
    g,
    [PF(x0, y0 + w, z), PF(x0 + w, y0 + w, z), PF(x0 + w, y0 + w, z + hh), PF(x0, y0 + w, z + hh)],
    col,
  );
  poly(
    g,
    [PF(x0 + w, y0 + w, z), PF(x0 + w, y0, z), PF(x0 + w, y0, z + hh), PF(x0 + w, y0 + w, z + hh)],
    cR,
  );
  poly(
    g,
    [
      PF(x0, y0, z + hh),
      PF(x0 + w, y0, z + hh),
      PF(x0 + w, y0 + w, z + hh),
      PF(x0, y0 + w, z + hh),
    ],
    cT,
  );
  if (rank === "lead") box(g, PF, [-2, -2, z + hh], [4, 4, 3.5], shade(col));
  if (rank === "verifier")
    box(g, PF, [x0 + w + 3, y0 + 1, z + 2], [2.5, 6, 5.5], shade(PALETTE.ink2));
  if (director) {
    [
      [-6, 3.5],
      [-2, 5],
      [2, 3.5],
    ].forEach(([dx = 0, ht = 0], i) =>
      box(g, PF, [dx, -2, z + hh], [4, 4, ht], shade(i === 1 ? col : dk(col, 0.12))),
    );
  }
  // Face on the left wall: a white panel, two eyes and a level mouth.
  const face = (u: number, v: number) => PF(x0 + u, y0 + w, z + hh - v);
  poly(g, [face(1.6, 2.3), face(w - 1.6, 2.3), face(w - 1.6, 9.9), face(1.6, 9.9)], PALETTE.white);
  for (const dx of [-2.55, 2.55]) {
    const [ex, ey] = face(w / 2 + dx, 5.5);
    g.circle(ex, ey, 1.1).fill({ color: PALETTE.ink });
  }
  const [mx0, my0] = face(w / 2 - 1.9, 8.1);
  const [mx1, my1] = face(w / 2 + 1.9, 8.1);
  g.moveTo(mx0, my0).lineTo(mx1, my1).stroke({ width: 0.9, color: PALETTE.ink, cap: "round" });
}
