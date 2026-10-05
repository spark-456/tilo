// S-01 "What Tilo would build" (artboard Tilo Home v2). Decorative isometric glyph plus three facts
// that are rules of the product, each from the PRD: world size by agent count (9.1), the run shown
// as it happens (9.6), and approval before anything spends, shares or cannot be undone (principles).
// No figure here is a forecast for a task: nothing has been planned yet (HR-1).
const TILES = [
  ["Size", "From 1–2 agents (an Outpost) to 16 or more (a City), set by the work"],
  ["You see", "Every step of the run as it happens, in the world and in words"],
  ["You approve", "Anything that spends, shares or can't be undone"],
] as const;

type Shades = readonly [top: string, left: string, right: string];
const pts = (...p: ReadonlyArray<readonly [number, number]>) => p.map((q) => q.join(",")).join(" ");

/** One block in the kit's look: one light, three face shades (top lightest), no outlines. */
function Block({ x, y, w, h, c }: { x: number; y: number; w: number; h: number; c: Shades }) {
  const t = y - h; // the top face's centre line
  return (
    <g>
      <polygon points={pts([x, t - w / 2], [x + w, t], [x, t + w / 2], [x - w, t])} fill={c[0]} />
      <polygon points={pts([x - w, t], [x, t + w / 2], [x, y + w / 2], [x - w, y])} fill={c[1]} />
      <polygon points={pts([x + w, t], [x, t + w / 2], [x, y + w / 2], [x + w, y])} fill={c[2]} />
    </g>
  );
}

const BRAND: Shades = [
  "var(--color-brand-primary)",
  "var(--color-brand-primary-lip)",
  "var(--color-ink-1)",
];
const PALE: Shades = ["var(--color-surface-1)", "var(--color-surface-2)", "var(--color-ink-2)"];

function Glyph() {
  return (
    <svg viewBox="0 0 240 132" aria-hidden="true" focusable="false" className="home-glyph">
      <polygon
        points={pts([120, 4], [236, 62], [120, 120], [4, 62])}
        fill="var(--color-surface-2)"
      />
      <polygon
        points={pts([120, 14], [218, 62], [120, 110], [22, 62])}
        fill="var(--color-surface-1)"
      />
      {/* A road between the blocks, then blocks back to front so nearer ones cover farther ones. */}
      <polygon
        points={pts([98, 80], [168, 62], [176, 66], [106, 84])}
        fill="var(--color-surface-2)"
      />
      <Block x={150} y={64} w={18} h={22} c={PALE} />
      <Block x={92} y={72} w={26} h={34} c={BRAND} />
      <Block x={186} y={74} w={12} h={8} c={PALE} />
      <Block x={52} y={78} w={14} h={12} c={PALE} />
      <Block x={150} y={92} w={14} h={10} c={PALE} />
      <Block x={120} y={100} w={10} h={6} c={PALE} />
    </svg>
  );
}

export function HomePreview() {
  return (
    <aside className="home-preview" aria-label="What Tilo would build">
      <div className="home-preview-head">
        {/* The sizes are the PRD 9.1 range; no figure here is about this task. */}
        <span className="home-tier">Outpost to City</span>
        <span className="home-preview-title">What Tilo would build</span>
      </div>
      <Glyph />
      <dl className="home-tiles">
        {TILES.map(([term, text]) => (
          <div key={term}>
            <dt>{term}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>
    </aside>
  );
}
