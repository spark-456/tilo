// The World, Story and Trace lenses of one world (PRD 9.6, 18.3): three links, one per screen.
import { AppLink } from "./AppLink";

const LENSES = [
  ["world", "World", ""],
  ["story", "Story", "/story"],
  ["trace", "Trace", "/trace"],
] as const;

export function LensTabs({
  worldId,
  current,
}: { worldId: string; current: (typeof LENSES)[number][0] }) {
  return (
    <nav className="lens-tabs" aria-label="Lens">
      {LENSES.map(([key, label, suffix]) => (
        <AppLink
          key={key}
          to={`/world/${encodeURIComponent(worldId)}${suffix}`}
          className="lens-tab"
          {...(key === current ? { "aria-current": "page" as const } : {})}
        >
          {label}
        </AppLink>
      ))}
    </nav>
  );
}
