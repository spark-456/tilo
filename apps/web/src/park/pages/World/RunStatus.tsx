// WORLD-USEFUL: the top of a real run's World page. One plain progress line, what the run assumed instead of
// asking (chips), the recorded reason a run stopped with "Start it again", and the delivered result, readable here
// with Open and Download. Every word comes from a recorded event (HR-1..HR-7); with no event it says so.
import { useState } from "react";
import type { Api } from "../../api";
import { openResult, saveResult } from "../../api/results";
import { Button } from "../../components";
import { Markdown } from "./markdown";
import { isRestartStop, restartApproval } from "./runProgress";
import type { RunView } from "./runView";
import type { RunEvent } from "./useRunEvents";
import { type ResultView, useRunResult } from "./useRunResult";

/** What the card needs to start a stopped run again: the one call, and where the new world is opened. */
export interface StartAgain {
  readonly start: () => Promise<{ readonly worldId: string }>;
  readonly open: (worldId: string) => void;
  /** Where a run the server will not restart goes instead: a fresh task on Home. */
  readonly newTask: () => void;
}

const refused = (error: unknown): boolean => {
  const status = (error as { status?: unknown } | null)?.status;
  return typeof status === "number" && status >= 400 && status < 500;
};

/** The one honest action for any stopped run (RERUN-1, RERUN-ANY): it always asks `/rerun` first; only a server
 * refusal points to a new task, and any other failure says so and leaves the button for another try. */
function StartItAgain({ again, events }: { again: StartAgain; events: readonly RunEvent[] }) {
  const { cap, sent } = restartApproval(events);
  const restart = isRestartStop(events);
  const [state, setState] = useState<"idle" | "busy" | "error" | "refused">("idle");
  const press = (): void => {
    if (state === "busy" || cap === null) return;
    setState("busy");
    again.start().then(
      (r) => again.open(r.worldId),
      (error: unknown) => setState(refused(error) ? "refused" : "error"),
    );
  };
  return (
    <div className="park-world-restart" data-testid="start-it-again">
      {restart ? (
        <p className="park-world-noruns">Tilo restarted while this was running, so it stopped.</p>
      ) : null}
      <p className="park-world-noruns">
        {sent > 0
          ? `The stopped run already sent things outside Tilo (${sent} recorded outbound ${sent === 1 ? "action" : "actions"}). Starting again may send them again.`
          : "No outbound sends are recorded for the stopped run. This does not confirm that nothing was sent."}
      </p>
      <p className="park-world-noruns">
        {cap === null
          ? "The spending cap is not available in the recorded events. Starting again is unavailable."
          : `Starting again approves a new run with a spending cap of ${cap} credits, in addition to any credits already used by the stopped run.`}
      </p>
      <Button
        variant="primary"
        onClick={press}
        disabled={cap === null || state === "busy"}
        aria-busy={state === "busy"}
      >
        {state === "busy" ? "Starting…" : "Start it again"}
      </Button>
      {state === "error" ? (
        <p className="park-world-noruns" role="alert">
          It could not be started just now. Nothing was started and nothing was charged. Try again
          in a minute.
        </p>
      ) : null}
      {state === "refused" ? (
        <div role="alert">
          <p className="park-world-noruns">
            Tilo cannot start this run again from here. Nothing was started and nothing was charged.
            Describe the task again to start a new run.
          </p>
          <Button variant="secondary" size="sm" onClick={again.newTask}>
            New task
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function ResultBody({ view, retry }: { view: ResultView; retry: () => void }) {
  if (view.status === "loading") return <p className="park-world-noruns">Loading the result…</p>;
  if (view.status === "error")
    return (
      <div role="alert">
        <p className="park-world-noruns">The result could not be loaded. Nothing is lost.</p>
        <Button variant="secondary" size="sm" onClick={retry}>
          Try again
        </Button>
      </div>
    );
  if (view.status === "file")
    return (
      <p className="park-world-noruns">
        {`The result is a file (${view.blob.type || "unknown type"}). Open or download it to read it.`}
      </p>
    );
  if (view.status !== "text") return null;
  return (
    // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling text box must be reachable by keyboard to be read
    <div className="park-world-resulttext" data-testid="result-text" tabIndex={0}>
      {view.kind === "markdown" ? (
        <Markdown text={view.text} />
      ) : (
        <pre className="park-world-resultpre">{view.text}</pre>
      )}
      {view.cut ? (
        <p className="park-world-sub">Showing the start. Download it for the rest.</p>
      ) : null}
    </div>
  );
}

/** The delivered result, read here; Open and Download are the same bytes the owner route serves (STUDIO-3: it sits
 * in the Result tab, where Share is the one filled button, so both are quiet). */
export function RunResult({ api, worldId }: { api: Api; worldId: string }) {
  const [attempt, setAttempt] = useState(0);
  const view = useRunResult(api, worldId, true, attempt);
  const blob = view.status === "text" || view.status === "file" ? view.blob : null;
  return (
    <section aria-label="Result" className="park-world-section" data-testid="run-result">
      {blob ? (
        <div className="park-world-resultactions">
          <span className="park-world-sub">Delivered by this run</span>
          <Button variant="secondary" size="sm" onClick={() => saveResult(blob, worldId)}>
            Download
          </Button>
          <Button variant="secondary" size="sm" onClick={() => openResult(blob)}>
            Open result
          </Button>
        </div>
      ) : (
        <span className="park-world-sub">Delivered by this run</span>
      )}
      <ResultBody view={view} retry={() => setAttempt((n) => n + 1)} />
    </section>
  );
}

/** What the run assumed instead of asking (FR-INT-04), as chips beside the tabs; nothing when none is recorded. */
export function AssumedChips({ assumptions }: { assumptions: readonly string[] }) {
  if (assumptions.length === 0) return null;
  return (
    <ul className="park-world-assumed" aria-label="What Tilo assumed instead of asking">
      {assumptions.map((a) => (
        <li key={a} className="park-world-assumedchip">{`Assumed: ${a}`}</li>
      ))}
    </ul>
  );
}

/** The one status banner: the progress line and bar, and a stopped run's recorded reason with "Start it again". The
 * assumptions sit beside the tabs (AssumedChips) and the result in the Result tab (RunResult). */
export function RunStatus({
  view,
  events,
  again,
}: {
  view: RunView;
  events: readonly RunEvent[];
  again?: StartAgain | undefined;
}) {
  return (
    <section
      aria-label="Run status"
      className="park-world-runstatus"
      data-phase={view.phase}
      data-testid="run-status"
    >
      <output className="park-world-runline">{view.line}</output>
      {view.percent !== null && view.phase !== "failed" ? (
        <progress
          className="park-world-progress"
          aria-label="Progress of the plan"
          max={100}
          value={view.percent}
        />
      ) : null}
      {view.failure ? (
        <div className="park-world-failed" data-testid="run-failed">
          <h2 className="park-world-h2">This run stopped</h2>
          <p className="park-world-failreason">{`Why: ${view.failure.reason}`}</p>
          {again ? <StartItAgain again={again} events={events} /> : null}
        </div>
      ) : null}
    </section>
  );
}
