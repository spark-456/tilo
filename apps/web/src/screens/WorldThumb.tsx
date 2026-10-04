// The thumbnail of a world on S-14: a still of the same isometric art the stage draws (the
// ported iso projection, palette and building styles of src/world/art), as SVG, from the layout
// and the events recorded so far (HR-1). A building not planned yet is not drawn; a planned one is
// a dashed outline and a one under construction is a low wall, so the state reads from the shape
// and not from colour alone (PRD 18.6). No new assets: this is a view of the world, not an icon.
import type { Layout } from "@tilo/contracts";
import { BASE, FLOOR } from "../world/art/building";
import { PALETTE, dk, lt, shade } from "../world/art/color";
import { P, type Pt } from "../world/art/iso";
import { type FrameBuilding, frameOf } from "../world/frame";
import type { WorldState } from "../world/reducer";

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

/** A still of the world, or nothing but its backdrop when the layout has no geometry. */
export function WorldThumb({ layout, state }: { layout: Layout; state: WorldState }) {
  const frame = frameOf(layout, state);
  const { x0, y0, x1, y1 } = frame.bounds;
  if (x1 <= x0 || y1 <= y0) return null;
  const order = [...frame.buildings].sort(
    (a, b) => a.lift - b.lift || a.rect.x + a.rect.y - (b.rect.x + b.rect.y),
  );
  return (
    <svg
      viewBox={`${x0} ${y0} ${x1 - x0} ${y1 - y0}`}
      preserveAspectRatio="xMidYMid meet"
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
            fill={lt(dist.tint, 0.7)}
          />
        );
      })}
      {order.map((b) => (
        <Building key={b.id} b={b} />
      ))}
    </svg>
  );
}
