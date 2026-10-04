// S-15 "Stop all autopilot" (PRD 10.4, FR-HIL-07): the one danger-styled control of the screen. It
// is a consequential action, so it asks first, in plain words, with nothing chosen for the person:
// opening the question focuses its heading, not a button. Only a second, deliberate press sends
// it. The page then says what the API answered and nothing before it (HR-1); a client that cannot
// send it shows the control disabled with the reason, never a live-looking no-op.
import { useEffect, useRef } from "react";
import { useClient } from "../api/ClientProvider";
import { canStopAutopilot, describeStop, useStopAutopilot } from "../world/autopilot";
import { Placeholder } from "./Placeholder";
import { nameOf } from "./kit";

export function StopAutopilot({ worldId }: { worldId: string }) {
  const client = useClient();
  const stop = useStopAutopilot(client, worldId);
  const heading = useRef<HTMLHeadingElement>(null);
  const ask = useRef<HTMLButtonElement>(null);
  const asked = useRef(false);
  // Focus follows the step: to the question's heading when it opens (no button is pre-focused) and
  // back to the control when it is cancelled, so a keyboard user never loses their place.
  useEffect(() => {
    if (stop.view === "confirming") {
      asked.current = true;
      heading.current?.focus();
    } else if (asked.current && (stop.view === "ready" || stop.view === "error")) {
      asked.current = false;
      ask.current?.focus();
    }
  }, [stop.view]);

  if (!canStopAutopilot(client)) {
    return <Placeholder label="Stop all autopilot" compact danger />;
  }
  const confirming = stop.view === "confirming" || stop.view === "sending";
  return (
    <div className="stop-autopilot" data-testid="stop-autopilot" data-stop={stop.view}>
      {confirming ? (
        <section className="stop-confirm" aria-labelledby="stop-confirm-title">
          <h3 id="stop-confirm-title" tabIndex={-1} ref={heading}>
            Stop all autopilot?
          </h3>
          <p>
            Every rule that runs on its own goes back to level L1, so each action waits for you
            again. Work that is already running keeps going. Pause all stops the agents too.
          </p>
          <div className="stop-actions">
            <button
              type="button"
              className="secondary danger"
              data-stop-control
              aria-busy={stop.view === "sending" ? "true" : undefined}
              aria-disabled={stop.view === "sending" ? "true" : undefined}
              onClick={() => {
                if (stop.view !== "sending") stop.confirm();
              }}
            >
              {stop.view === "sending" ? "Stopping…" : "Stop all autopilot"}
            </button>
            <button
              type="button"
              className="secondary"
              data-stop-control
              aria-disabled={stop.view === "sending" ? "true" : undefined}
              onClick={() => {
                if (stop.view !== "sending") stop.cancel();
              }}
            >
              Keep autopilot as it is
            </button>
          </div>
        </section>
      ) : (
        <button
          type="button"
          className="secondary danger"
          data-stop-control
          ref={ask}
          onClick={stop.ask}
        >
          Stop all autopilot
        </button>
      )}
      {/* biome-ignore lint/a11y/useSemanticElements: a live status region, not a form result. */}
      <p className="stop-note" role="status" data-testid="stop-result">
        {stop.view === "done" && stop.result && (
          <>
            {describeStop(stop.result)}
            {stop.result.confirmations.length > 0 &&
              ` Confirmations go to: ${stop.result.confirmations.map((c) => nameOf(c.channel)).join(", ")}.`}
          </>
        )}
        {stop.view === "error" && stop.error}
      </p>
    </div>
  );
}
