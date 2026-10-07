// The World, Story and Trace lenses of one world (PRD 9.6, 18.3): three links, one per screen, and
// under them the selection all three share (FR-WLD-06).
import { stagePath } from "../router";
import { AppLink } from "./AppLink";
import { SelectionBar } from "./SelectionBar";

// The World tab is the live stage at /world/:id/stage (/world/:id is the Park overview since WEB-CUTOVER).
const LENSES = [
  ["world", "World"],
  ["story", "Story"],
  ["trace", "Trace"],
] as const;

const lensPath = (worldId: string, key: (typeof LENSES)[number][0]): string =>
  key === "world"
    ? stagePath(worldId)
    : key === "story"
      ? `/world/${encodeURIComponent(worldId)}/story`
      : `/world/${encodeURIComponent(worldId)}/trace`;

export function LensTabs({
  worldId,
  current,
}: { worldId: string; current: (typeof LENSES)[number][0] }) {
  return (
    <>
      <nav className="lens-tabs" aria-label="Lens">
        {LENSES.map(([key, label]) => (
          <AppLink
            key={key}
            to={lensPath(worldId, key)}
            className="lens-tab"
            {...(key === current ? { "aria-current": "page" as const } : {})}
          >
            {label}
          </AppLink>
        ))}
      </nav>
      <SelectionBar worldId={worldId} />
    </>
  );
}
