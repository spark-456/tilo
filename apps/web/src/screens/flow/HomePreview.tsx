// S-01 "What Tilo would build" (artboard Tilo Home v2). A static isometric village (HomeScene) plus three facts
// that are rules of the product, each from the PRD: world size by agent count (9.1), the run shown
// as it happens (9.6), and approval before anything spends, shares or cannot be undone (principles).
// No figure here is a forecast for a task: nothing has been planned yet (HR-1).
import { HomeScene } from "./HomeScene";

const TILES = [
  ["Size", "From 1–2 agents (an Outpost) to 16 or more (a City), set by the work"],
  ["You see", "Every step of the run as it happens, in the world and in words"],
  ["You approve", "Anything that spends, shares or can't be undone"],
] as const;

export function HomePreview() {
  return (
    <aside className="home-preview" aria-label="What Tilo would build">
      <div className="home-preview-head">
        {/* The sizes are the PRD 9.1 range; no figure here is about this task. */}
        <span className="home-tier">Outpost to City</span>
        <span className="home-preview-title">What Tilo would build</span>
      </div>
      <div className="home-stage">
        <HomeScene />
      </div>
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
