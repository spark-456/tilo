// FR-WLD-08 Replay region (PRD 9.6, 18.3): scrub a finished run to any event, with the HR-4 banner
// ("Replay of run #… recorded <date>") above it. One native range input, so the arrow keys, Home,
// End and a screen reader's slider all work; one stop per event. Scrubbing only moves the shared
// replay point (world/replay.ts): the World shows stateAt(seq), Story and Trace the events up to
// it. A live run cannot be scrubbed, and the reason is on screen. The region is one reserved box
// (CLS): the banner and the reason share a slot, so a run finishing moves nothing.
import type { Event } from "@tilo/contracts";
import { type CSSProperties, useMemo } from "react";
import { useClient } from "../api/ClientProvider";
import { scrubMarks } from "../world/levels";
import {
  indexToPoint,
  pointToIndex,
  replayBanner,
  scrubText,
  setReplayPoint,
  useReplayPoint,
} from "../world/replay";
import { useRunLog } from "../world/runLog";
import { runEnded, worldStatus } from "../world/runSummary";

export function ReplayScrubber({
  worldId,
  events,
  finished,
  fixture,
}: {
  worldId: string;
  events: readonly Event[];
  /** The run has ended (it will record nothing more), so every stop exists. */
  finished: boolean;
  fixture: boolean;
}) {
  const point = useReplayPoint(worldId);
  const last = events.length;
  const index = pointToIndex(events, point);
  const go = (to: number) => setReplayPoint(worldId, indexToPoint(events, to));
  const text = scrubText(events, index);
  const marks = useMemo(() => scrubMarks(events), [events]);
  const banner = finished ? replayBanner(events, fixture) : null;
  return (
    <section className="replay-dock" aria-label="Replay" data-testid="replay-scrubber">
      {banner ? (
        // biome-ignore lint/a11y/useSemanticElements: a persistent mode banner, not a form result (same as App.tsx's fixture banner).
        <p className="replay-banner" role="status" data-testid="replay-banner">
          {banner}
        </p>
      ) : (
        <p className="replay-banner" data-testid="scrub-reason">
          {finished
            ? "This run recorded no events, so there is nothing to replay."
            : "Replay opens once this run has finished. It is still going."}
        </p>
      )}
      <div className="replay-row">
        <button
          type="button"
          className="replay-step"
          data-lens-control
          aria-label="Previous event"
          disabled={!finished || index <= 0}
          onClick={() => go(index - 1)}
        >
          ‹
        </button>
        <div className="replay-track">
          <input
            type="range"
            aria-label="Replay position"
            aria-valuetext={finished ? text : "Not available while the run is going"}
            min={0}
            max={last}
            step={1}
            value={index}
            disabled={!finished || last === 0}
            onChange={(e) => go(Number(e.currentTarget.value))}
          />
          {/* Where the run asked for a decision, finished a level or hit a problem: the same
              events the position text names, drawn on the track. Decoration, never a control. */}
          <span className="replay-marks" aria-hidden="true" data-testid="scrub-marks">
            {finished &&
              marks.map((m) => (
                <i
                  key={m.index}
                  data-kind={m.kind}
                  style={{ "--at": m.index / last } as CSSProperties}
                />
              ))}
          </span>
        </div>
        <button
          type="button"
          className="replay-step"
          data-lens-control
          aria-label="Next event"
          disabled={!finished || index >= last}
          onClick={() => go(index + 1)}
        >
          ›
        </button>
      </div>
      <p className="replay-pos">{finished ? text : "Position: not available yet"}</p>
    </section>
  );
}

/** The scrubber of a world the client serves: its run log, and whether the log has ended. */
export function LoggedScrubber({ worldId, fixture }: { worldId: string; fixture: boolean }) {
  const events = useRunLog(useClient(), worldId);
  return (
    <ReplayScrubber
      worldId={worldId}
      events={events}
      finished={runEnded(worldStatus(events))}
      fixture={fixture}
    />
  );
}
