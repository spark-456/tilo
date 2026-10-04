// FR-WLD-07: the Pause all control and the "Paused" banner, one fixed-height slot in the HUD (PRD
// 9.5 world.paused: "A Paused banner shows with Resume"). The slot keeps its box in every state, so
// nothing around it moves. Pause all is a request: only a recorded world.paused shows "Paused" (HR-1).
// Resume has no client call yet, so it is an aria-disabled "Coming soon" control, never a dead click.
import { useClient } from "../api/ClientProvider";
import { type PauseView, usePause } from "../world/pause";
import { useRunStatus } from "../world/runLog";
import type { RunStatus } from "../world/runSummary";

const NOTE: Record<PauseView, string> = {
  ready: "Stops every agent.",
  pausing: "Pausing…",
  unconfirmed: "No confirmation recorded yet. Agents may still be working. You can try again.",
  error: "",
  unavailable: "Coming soon: this connection cannot pause yet.",
  paused: "All work is paused.",
  ended: "This run has ended.",
};

const REPLAY_NOTE = "A recorded replay cannot be paused.";

function Slot({ view, note, onPause }: { view: PauseView; note: string; onPause: () => void }) {
  const blocked =
    view === "pausing" || view === "unavailable" || view === "paused" || view === "ended";
  return (
    <section
      className="pause-slot"
      aria-label="Pause all"
      data-testid="pause-slot"
      data-pause={view}
    >
      <div className="pause-row">
        <button
          type="button"
          className="secondary pause-btn"
          data-testid="pause-all"
          data-pause-control
          aria-disabled={blocked ? "true" : undefined}
          aria-busy={view === "pausing" ? "true" : undefined}
          title={view === "unavailable" ? note : undefined}
          onClick={() => {
            if (!blocked) onPause();
          }}
        >
          Pause all
        </button>
        {view === "paused" && (
          <button
            type="button"
            className="secondary pause-btn"
            data-testid="resume"
            aria-disabled="true"
            title="Coming soon"
            onClick={(e) => e.preventDefault()}
          >
            Resume
          </button>
        )}
      </div>
      {/* biome-ignore lint/a11y/useSemanticElements: a live status region, not a form result. */}
      <p className="pause-note" role="status">
        {note}
      </p>
    </section>
  );
}

/** The slot for a world the client runs: Pause all goes through the client when it can. */
export function WorldPauseSlot({ worldId, confirmMs }: { worldId: string; confirmMs?: number }) {
  const client = useClient();
  const status = useRunStatus(client, worldId);
  const { view, error, pause } = usePause(client, worldId, status, confirmMs);
  return <Slot view={view} note={view === "error" ? (error ?? "") : NOTE[view]} onPause={pause} />;
}

/** The slot beside a recorded replay (?fixture=): no client is running it, so it cannot be paused,
 * but a world.paused recorded in the stream still shows Paused. */
export function ReplayPauseSlot({ status }: { status: RunStatus }) {
  const view: PauseView =
    status === "paused"
      ? "paused"
      : status === "completed" || status === "failed"
        ? "ended"
        : "unavailable";
  return (
    <Slot
      view={view}
      note={view === "unavailable" ? REPLAY_NOTE : NOTE[view]}
      onPause={() => undefined}
    />
  );
}
