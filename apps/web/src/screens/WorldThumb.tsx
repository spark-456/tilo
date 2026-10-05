// The thumbnail of a world on S-14: a still of the same isometric art the stage draws (the
// ported iso projection, palette and building styles of src/world/art), as SVG, from the layout
// and the events recorded so far (HR-1). A building not planned yet is not drawn; a planned one is
// a dashed outline and a one under construction is a low wall, so the state reads from the shape
// and not from colour alone (PRD 18.6). Agents stand where the run has put them, drawn larger than
// life so a figure still reads in a card (a rank shows by shape: director crest, lead cap, verifier
// clipboard). No new assets: this is a view of the world, not an icon.
import type { Layout } from "@tilo/contracts";
import tokens from "../design/tokens";
import { BASE, FLOOR } from "../world/art/building";
import { PALETTE, dk, lt, shade } from "../world/art/color";
import { P, type Pt } from "../world/art/iso";
import { type FrameAgent, type FrameBuilding, frameOf } from "../world/frame";
import type { WorldState } from "../world/reducer";

/** Larger than life: at a card's scale a true-size figure is a few pixels. */
const AGENT_SCALE = 2.4;
const pts = (ps: readonly Pt[]): string =>
  ps.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");

function Building({ b }: { b: FrameBuilding }) {
  const { x, y, w, d } = b.rect;
  const corner = (dx: number, dy: number, z = 0): Pt => P(x + dx, y + dy, b.lift + z);
  const ground = [corner(0, 0), corner(w, 0), corner(w, d), corner(0, d)];
  if (b.status === "planned") {
    return (
      <polygon
        points={pts(ground)}
        fill={lt(b.tint, 0.85)}
        stroke={b.tint}
        strokeWidth={2}
        strokeDasharray="5 4"
      />
    );
  }
  const full = b.status !== "constructing";
  const h = full ? BASE + (b.floors - 1) * FLOOR : BASE / 3;
  const c = shade(lt(b.tint, 0.8));
  const top = [corner(0, 0, h), corner(w, 0, h), corner(w, d, h), corner(0, d, h)];
  return (
    <g>
      <polygon
        points={pts([corner(0, d), corner(w, d), corner(w, d, h), corner(0, d, h)])}
        fill={c.l}
      />
      <polygon
        points={pts([corner(w, d), corner(w, 0), corner(w, 0, h), corner(w, d, h)])}
        fill={c.r}
      />
      <polygon
        points={pts(top)}
        fill={full ? b.tint : c.t}
        stroke={dk(b.tint, 0.2)}
        strokeWidth={0.7}
      />
    </g>
  );
}

/** An agent figure drawn with its feet at the origin: a body, a white face with two eyes, and a
 * rank mark. The same figure stands in the thumbnail and beside a name in the crew strip. */
export function AgentFigure({ rank, tint }: { rank: string; tint: string }) {
  const director = rank === "director";
  const col = director ? tokens.color.brand.primary : tint;
  const [w, h] = director ? [20, 28] : [18, 26];
  const [x, y] = [-w / 2, -h - 2];
  const edge = dk(col, 0.3);
  return (
    <>
      <ellipse rx={w * 0.7} ry={4} fill={PALETTE.ink} opacity={0.15} />
      {director && (
        <g fill={dk(col, 0.12)}>
          {[-6, -1, 4].map((dx, i) => (
            <rect key={dx} x={dx} y={y - (i === 1 ? 7 : 5)} width={4} height={6} />
          ))}
        </g>
      )}
      {rank === "lead" && <rect x={-4} y={y - 5} width={8} height={6} fill={shade(col).l} />}
      {rank === "verifier" && (
        <rect x={x + w + 1} y={y + 8} width={5} height={10} fill={PALETTE.ink2} stroke={edge} />
      )}
      <rect x={x} y={y} width={w} height={h} rx={4} fill={col} stroke={edge} strokeWidth={1.2} />
      <rect x={x + 3} y={y + 4} width={w - 6} height={11} rx={2.5} fill={PALETTE.white} />
      <circle cx={-3.2} cy={y + 9} r={1.5} fill={PALETTE.ink} />
      <circle cx={3.2} cy={y + 9} r={1.5} fill={PALETTE.ink} />
    </>
  );
}

function Agent({ a }: { a: FrameAgent }) {
  return (
    <g
      transform={`translate(${a.cx.toFixed(1)} ${a.cy.toFixed(1)}) scale(${AGENT_SCALE})`}
      data-testid="thumb-agent"
      data-rank={a.rank}
    >
      <AgentFigure rank={a.rank} tint={a.tint} />
    </g>
  );
}

/** A still of the world, or nothing but its backdrop when the layout has no geometry. */
export function WorldThumb({ layout, state }: { layout: Layout; state: WorldState }) {
  const frame = frameOf(layout, state);
  if (frame.plates.length === 0) return null;
  const order = [...frame.buildings].sort(
    (a, b) => a.lift - b.lift || a.rect.x + a.rect.y - (b.rect.x + b.rect.y),
  );
  // A tight box round what is drawn (plates and the tops of the buildings), so the world fills the
  // thumbnail instead of floating in the stage's padding.
  const at = (r: { x: number; y: number; w: number; d: number }, z: number): Pt[] => [
    P(r.x, r.y, z),
    P(r.x + r.w, r.y, z),
    P(r.x + r.w, r.y + r.d, z),
    P(r.x, r.y + r.d, z),
  ];
  const drawn = [
    ...frame.plates.flatMap((p) => at(p.rect, p.lift)),
    ...frame.buildings.flatMap((b) => at(b.rect, b.lift + BASE + (b.floors - 1) * FLOOR)),
    ...frame.agents.flatMap((a): Pt[] => [
      [a.cx - 14 * AGENT_SCALE, a.cy - 40 * AGENT_SCALE],
      [a.cx + 14 * AGENT_SCALE, a.cy + 6 * AGENT_SCALE],
    ]),
  ];
  const xs = drawn.map((q) => q[0]);
  const ys = drawn.map((q) => q[1]);
  const [x0, y0] = [Math.min(...xs) - 8, Math.min(...ys) - 8];
  const [w, h] = [Math.max(...xs) + 8 - x0, Math.max(...ys) + 8 - y0];
  return (
    <svg
      viewBox={`${x0} ${y0} ${w} ${h}`}
      preserveAspectRatio="xMidYMax meet"
      aria-hidden="true"
      focusable="false"
    >
      {frame.plates.map((p) => {
        const { x, y, w, d } = p.rect;
        const corner = (dx: number, dy: number): Pt => P(x + dx, y + dy, p.lift);
        return (
          <polygon
            key={p.id}
            points={pts([corner(0, 0), corner(w, 0), corner(w, d), corner(0, d)])}
            fill={PALETTE.slab.t}
            stroke={PALETTE.slab.r}
            strokeWidth={1}
          />
        );
      })}
      {frame.districts.map((dist) => {
        const { x, y, w, d } = dist.rect;
        const corner = (dx: number, dy: number): Pt => P(x + dx, y + dy, dist.lift);
        return (
          <polygon
            key={dist.id}
            points={pts([corner(0, 0), corner(w, 0), corner(w, d), corner(0, d)])}
            fill={lt(dist.tint, 0.5)}
            stroke={dist.tint}
            strokeWidth={1.5}
          />
        );
      })}
      {order.map((b) => (
        <Building key={b.id} b={b} />
      ))}
      {[...frame.agents]
        .sort((a, b) => a.level - b.level || a.cy - b.cy)
        .map((a) => (
          <Agent key={a.id} a={a} />
        ))}
    </svg>
  );
}
