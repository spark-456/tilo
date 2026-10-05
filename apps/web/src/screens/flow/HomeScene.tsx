// S-01 "What Tilo would build": a small static isometric village, drawn as SVG (artboard Tilo Home v2
// shows the same kit at the Outpost tier). Ported and trimmed from design/source/tilo-world.js
// (P, poly, box, colorsFor, facade, roofEl, tree, label; ADR-0003) and from the Pixi art in
// src/world/art, with SVG polygons in place of Graphics paths. Every colour is a design token or a
// mix of one with black or white. It is a picture of the product, not of a task: nothing in it is
// planned, nothing moves (HR-1, HR-2), and no figure or agent is drawn.
import type { ReactNode } from "react";
import tokens from "../../design/tokens";
import { PALETTE, type Shade, dk, lt } from "../../world/art/color";

type Pt = readonly [number, number];
const S = 0.55; // the stage's 64 x 32 tile, scaled so a 12 px label stays 12 px in a 320 px panel
const TW = tokens.stage.tileWidth * S;
const TH = tokens.stage.tileHeight * S;
const P = (x: number, y: number, z = 0): Pt => [((x - y) * TW) / 2, ((x + y) * TH) / 2 - z];
const pts = (a: readonly Pt[]) => a.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");

/** A polygon with a same-colour hairline, which closes the seams between faces. */
const Poly = ({ a, c }: { a: readonly Pt[]; c: string }) => (
  <polygon points={pts(a)} fill={c} stroke={c} strokeWidth={0.7} strokeLinejoin="round" />
);

type Box = readonly [x: number, y: number, z: number, w: number, d: number, h: number];
function Slab({ b, c }: { b: Box; c: Shade }) {
  const [x, y, z, w, d, h] = b;
  return (
    <>
      <Poly
        a={[P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)]}
        c={c.l}
      />
      <Poly
        a={[P(x + w, y + d, z), P(x + w, y, z), P(x + w, y, z + h), P(x + w, y + d, z + h)]}
        c={c.r}
      />
      <Poly
        a={[P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)]}
        c={c.t}
      />
    </>
  );
}

type Roof = "flat" | "gable" | "dome";
interface Spot {
  name: string;
  x: number;
  y: number;
  w: number;
  d: number;
  floors: number;
  tint: string;
  roof: Roof;
}
const WALL = 26 * S;
const FLOOR = 20 * S;

function Building({ s }: { s: Spot }) {
  const { x, y, w, d, floors, tint, roof } = s;
  const wl = lt(tint, 0.8);
  const wall: Shade = { l: wl, r: dk(wl, 0.15), t: lt(wl, 0.35) };
  const hb = WALL + (floors - 1) * FLOOR;
  const win = lt(tint, 0.45);
  const rows = Array.from({ length: floors }, (_, f) => 5 * S + f * FLOOR);
  const pane = (
    key: string | number,
    side: "L" | "R",
    u0: number,
    u1: number,
    v0: number,
    v1: number,
    c: string,
  ) => {
    const q = (u: number, v: number) =>
      side === "L" ? P(x + u * w, y + d, 3 + v) : P(x + w, y + d - u * d, 3 + v);
    return <Poly key={key} a={[q(u0, v0), q(u1, v0), q(u1, v1), q(u0, v1)]} c={c} />;
  };
  const zt = 3 + hb; // the wall top
  const ridge = (t: number): Pt => P(x + w * t, y + d / 2, zt + 11 * S + 6 * d * S);
  return (
    <g>
      <Slab b={[x, y, 3, w, d, hb]} c={wall} />
      {rows.map((v) => (
        <g key={v}>
          {[0.2, 0.55, 0.85].map((u) => pane(u, "L", u - 0.08, u + 0.08, v, v + 11 * S, win))}
          {[0.3, 0.7].map((u) => pane(u + 9, "R", u - 0.1, u + 0.1, v, v + 11 * S, win))}
        </g>
      ))}
      {pane("door", "L", 0.38, 0.5, 0, 15 * S, dk(tint, 0.45))}
      {roof === "flat" && (
        <Slab
          b={[x - 0.05, y - 0.05, zt, w + 0.1, d + 0.1, 5 * S]}
          c={{ t: lt(tint, 0.22), l: tint, r: dk(tint, 0.24) }}
        />
      )}
      {roof === "gable" && (
        <>
          <Poly a={[P(x, y + d, zt), P(x + w, y + d, zt), ridge(1), ridge(0)]} c={lt(tint, 0.14)} />
          <Poly a={[P(x + w, y + d, zt), P(x + w, y, zt), ridge(1)]} c={dk(tint, 0.24)} />
        </>
      )}
      {roof === "dome" && (
        <Dome at={P(x + w / 2, y + d / 2, zt)} r={Math.min(w, d) * TW * 0.36} tint={tint} />
      )}
    </g>
  );
}

/** A dome as lit and shaded halves, each a quarter ellipse above the base and a quarter below it. */
function Dome({ at: [cx, cy], r, tint }: { at: Pt; r: number; tint: string }) {
  const [h, f, shaded] = [r * 0.95, r / 2, dk(tint, 0.24)];
  const half = (sx: 1 | -1) =>
    `M${cx + sx * r} ${cy} A${r} ${h} 0 0 ${sx > 0 ? 0 : 1} ${cx} ${cy - h} V${cy + f} A${r} ${f} 0 0 ${sx > 0 ? 0 : 1} ${cx + sx * r} ${cy} Z`;
  return (
    <>
      <path d={half(-1)} fill={tint} />
      <path d={half(1)} fill={shaded} />
    </>
  );
}

/** A tree, as the stage draws it: a trunk, then a round crown or a pine in two shades. */
function Tree({ at, pine }: { at: readonly [number, number]; pine: boolean }) {
  const crown = lt(tokens.color.district.accounts, 0.45);
  const [px, py] = P(at[0], at[1], 3);
  const s = S * 5;
  return (
    <g>
      <rect x={px - 1} y={py - 4} width={2} height={4} fill={dk(PALETTE.scaffold, 0.2)} />
      {pine ? (
        <>
          <polygon
            points={pts([
              [px - s * 1.1, py - 3],
              [px, py - 3 - s * 2.7],
              [px, py - 3 + s * 0.4],
            ])}
            fill={crown}
          />
          <polygon
            points={pts([
              [px + s * 1.1, py - 3],
              [px, py - 3 - s * 2.7],
              [px, py - 3 + s * 0.4],
            ])}
            fill={dk(crown, 0.18)}
          />
        </>
      ) : (
        <>
          <ellipse cx={px - s * 0.3} cy={py - 5 - s} rx={s * 0.95} ry={s * 1.1} fill={crown} />
          <ellipse
            cx={px + s * 0.55}
            cy={py - 5 - s}
            rx={s * 0.8}
            ry={s * 1.1}
            fill={dk(crown, 0.18)}
          />
        </>
      )}
    </g>
  );
}

/** A name tag: white pill, ink text, 12 px (the ramp's smallest step). */
function Tag({
  at: [x, y],
  text,
  fill = PALETTE.white,
  ink = PALETTE.ink,
}: { at: Pt; text: string; fill?: string; ink?: string }) {
  const w = text.length * 6.6 + 16;
  return (
    <g>
      <rect
        x={x - w / 2}
        y={y - 10}
        width={w}
        height={20}
        rx={10}
        fill={fill}
        stroke={PALETTE.pillLine}
        strokeWidth={1.5}
      />
      <text
        x={x}
        y={y + 4}
        textAnchor="middle"
        fontFamily={tokens.font.ui}
        fontSize={12}
        fontWeight={700}
        fill={ink}
      >
        {text}
      </text>
    </g>
  );
}

const ROAD = dk(PALETTE.road, 0.1);
const PLATE = { x0: -0.5, y0: -0.5, x1: 7.6, y1: 6.5 };
const SPOTS: readonly Spot[] = [
  {
    name: "Town Hall",
    x: 1.4,
    y: 0.7,
    w: 2.4,
    d: 1.7,
    floors: 2,
    tint: tokens.color.district.hall,
    roof: "dome",
  },
  {
    name: "Library",
    x: 5,
    y: 0.6,
    w: 1.8,
    d: 1.8,
    floors: 2,
    tint: tokens.color.district.research,
    roof: "gable",
  },
  {
    name: "Delivery Dock",
    x: 5.2,
    y: 4.3,
    w: 1.9,
    d: 1.2,
    floors: 1,
    tint: tokens.color.district.delivery,
    roof: "flat",
  },
  {
    name: "Workshop",
    x: 0.8,
    y: 4.2,
    w: 1.8,
    d: 1.6,
    floors: 1,
    tint: tokens.color.district.analysis,
    roof: "gable",
  },
];
const TREES: readonly (readonly [number, number, boolean])[] = [
  [-0.1, 2.6, true],
  [3.8, 0.3, false],
  [4.1, 2.6, true],
  [7.2, 3.1, true],
  [3.6, 3.9, false],
  [3.4, 5.9, true],
  [0.2, 6.0, false],
  [7.3, 6.0, false],
  [7.4, 0.4, true],
];
const ROOF_UP = { flat: 5, gable: 22, dome: 28 } as const;
/** Over the roof's middle for the back row; on the ground in front for the front row, so a tag
 * never sits on a wall or on the building behind. */
const tag = (s: Spot): Pt =>
  s.y > 3
    ? P(s.x + s.w / 2, s.y + s.d + 0.75, 3)
    : P(s.x + s.w / 2, s.y + s.d / 2, 3 + WALL + (s.floors - 1) * FLOOR + ROOF_UP[s.roof] * S + 26);

export function HomeScene(): ReactNode {
  const { x0, y0, x1, y1 } = PLATE;
  const [left, right, top, bottom] = [
    P(x0, y1)[0],
    P(x1, y0)[0],
    P(x0, y0)[1] - 50,
    P(x1, y1)[1] + 14,
  ];
  const patch = (r: { x: number; y: number; w: number; d: number }, tint: string) => (
    <Slab
      b={[r.x, r.y, 0, r.w, r.d, 3]}
      c={{ t: lt(tint, 0.78), l: lt(tint, 0.42), r: lt(tint, 0.3) }}
    />
  );
  const sorted = [...SPOTS].sort((a, b) => a.x + a.y - (b.x + b.y));
  return (
    <svg
      viewBox={`${left - 8} ${top} ${right - left + 16} ${bottom - top}`}
      aria-hidden="true"
      focusable="false"
      className="home-scene"
    >
      <Slab b={[x0, y0, -8, x1 - x0, y1 - y0, 8]} c={PALETTE.slab} />
      {patch({ x: 0.9, y: 0.1, w: 3.4, d: 2.7 }, tokens.color.district.hall)}
      {patch({ x: 4.6, y: 0.1, w: 2.8, d: 2.7 }, tokens.color.district.research)}
      {patch({ x: 0.3, y: 3.6, w: 2.8, d: 2.7 }, tokens.color.district.analysis)}
      {patch({ x: 4.6, y: 3.6, w: 2.8, d: 2.7 }, tokens.color.district.delivery)}
      {/* The roads: one along the plate, one across. */}
      <Poly
        a={[P(-0.3, 2.95, 3.2), P(7.4, 2.95, 3.2), P(7.4, 3.5, 3.2), P(-0.3, 3.5, 3.2)]}
        c={ROAD}
      />
      <Poly
        a={[P(4.28, -0.2, 3.2), P(4.62, -0.2, 3.2), P(4.62, 6.3, 3.2), P(4.28, 6.3, 3.2)]}
        c={ROAD}
      />
      {TREES.filter(([, y]) => y < 3).map(([x, y, pine]) => (
        <Tree key={`${x},${y}`} at={[x, y]} pine={pine} />
      ))}
      {sorted.map((s) => (
        <Building key={s.name} s={s} />
      ))}
      {TREES.filter(([, y]) => y >= 3).map(([x, y, pine]) => (
        <Tree key={`${x},${y}`} at={[x, y]} pine={pine} />
      ))}
      {SPOTS.map((s) => (
        <Tag key={s.name} at={tag(s)} text={s.name} />
      ))}
    </svg>
  );
}
