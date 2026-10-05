// The "Needs you" block of the right rail (PRD 18.3) on screens that read the replayed run: the
// same queue as S-06, from the same events (HR-1), so the rail never says "Nothing needs you"
// while a card waits. Each row opens the queue.
import { AppLink } from "../screens/AppLink";
import { useFixtureRun } from "../screens/kit";
import { useRunWorld, withWorld } from "../world/worldContext";
import { type QueueItem, deriveQueue, rungOf } from "./queue";

/** With no run to read (a live API, nothing started), the rail says nothing needs you and asks for nothing. */
export function NeedsYouRail() {
  return useRunWorld() === null ? <RailBox items={[]} worldId="" /> : <RailOfRun />;
}

function RailOfRun() {
  const { events, worldId } = useFixtureRun();
  return <RailBox items={deriveQueue(events)} worldId={worldId} />;
}

function RailBox({ items, worldId }: { items: QueueItem[]; worldId: string }) {
  return (
    <>
      <h2>Needs you</h2>
      {/* A fixed box: a card arriving or closing moves nothing below it (UX-1, CLS). */}
      {/* biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard reachable (WCAG 2.1.1). */}
      <section className="rail-needs" aria-label="Needs you list" tabIndex={0}>
        {items.length === 0 ? (
          <p data-testid="rail-needs-empty">Nothing needs you.</p>
        ) : (
          <ul className="rows" data-testid="rail-needs">
            {items.map((item) => (
              <li key={item.cardId}>
                <AppLink className="row" to={withWorld("/needs-you", worldId)}>
                  <span className="row-name">{item.opened.summary}</span>
                  <span className="row-state">{rungOf(item).label}</span>
                </AppLink>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
