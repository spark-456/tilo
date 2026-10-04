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
      <Block x={92} y={76} w={26} h={30} c={BRAND} />
      <Block x={150} y={80} w={20} h={18} c={PALE} />
      <Block x={128} y={96} w={14} h={10} c={PALE} />
    </svg>
  );
}

export function HomePreview() {
  return (
    <aside className="home-preview" aria-label="What Tilo would build">
      <p className="home-preview-title">What Tilo would build</p>
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
