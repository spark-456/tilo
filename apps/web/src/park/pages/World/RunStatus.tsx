// WORLD-USEFUL: the top of a real run's World page. One plain progress line, what the run assumed instead of
// asking (chips), the recorded reason a run stopped with "Try again", and the delivered result, readable here
// with Open and Download. Every word comes from a recorded event (HR-1..HR-7); with no event it says so.
import { useState } from "react";
import { ResultTab } from "../../../worldView/LiveStageEmbed";
import type { Api } from "../../api";
import { openResult, readResult, saveResult } from "../../api/results";
import { Button } from "../../components";
import { BrowserSteps } from "../../shared/BrowserSteps";
import { type SharedResult, resultHeadline } from "./ResultPanel";
import { Markdown } from "./markdown";
import { isRestartStop, restartApproval } from "./runProgress";
import type { RunView } from "./runView";
import type { RunEvent } from "./useRunEvents";
import type { ResultView } from "./useRunResult";

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
function StartItAgain({
  again,
  events,
  paused = false,
}: { again: StartAgain; events: readonly RunEvent[]; paused?: boolean }) {
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
          ? `The ${paused ? "paused" : "stopped"} run already sent things outside Tilo (${sent} recorded outbound ${sent === 1 ? "action" : "actions"}). Starting again may send them again.`
          : `No outbound sends are recorded for the ${paused ? "paused" : "stopped"} run. This does not confirm that nothing was sent.`}
      </p>
      <p className="park-world-noruns">
        {cap === null
          ? "The spending cap is not available in the recorded events. Starting again is unavailable."
          : `Starting again approves a new run with a spending cap of ${cap} credits, in addition to any credits already used by the ${paused ? "paused" : "stopped"} run.`}
      </p>
      <Button
        variant="primary"
        onClick={press}
        disabled={cap === null || state === "busy"}
        aria-busy={state === "busy"}
      >
        {state === "busy" ? "Starting…" : paused ? "Continue" : "Try again"}
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

interface DeliveredFile {
  readonly id: string;
  readonly name: string;
}

const FORMAT_NAMES: Readonly<Record<string, string>> = {
  email: "Email",
  google_docs: "Google Doc",
  google_sheets: "Spreadsheet",
  google_slides: "Slide deck",
  website: "Website",
};

function safeDeliverableName(value: string): string | null {
  const clean = value
    .replace(/\p{Cc}/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (
    !clean ||
    /\b(?:art|world|run)_[a-z0-9_]+\b/i.test(clean) ||
    /\b[0-7][0-9A-HJKMNP-TV-Z]{25}\b/.test(clean) ||
    /\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b/.test(clean)
  )
    return null;
  return clean.slice(0, 80);
}

function deliveredName(event: RunEvent, id: string): string {
  const data = event.data as { artifact?: { label?: unknown }; format?: unknown } | undefined;
  const label = data?.artifact?.label;
  const cleanLabel = typeof label === "string" ? safeDeliverableName(label) : null;
  if (cleanLabel && cleanLabel !== id) return cleanLabel;
  const fromSummary = event.summary.match(
    /^(?:The |Your )?(.+?) (?:is ready|was delivered)(?: in Tilo)?\.?$/i,
  );
  const cleanSummary = fromSummary?.[1] ? safeDeliverableName(fromSummary[1]) : null;
  if (cleanSummary && !/^item$/i.test(cleanSummary)) return cleanSummary;
  return (typeof data?.format === "string" && FORMAT_NAMES[data.format]) || "Delivered file";
}

/** RESULT-LIVE: distinct, named items recorded as delivered, in delivery order. */
function deliveredFiles(events: readonly RunEvent[]): DeliveredFile[] {
  const items: DeliveredFile[] = [];
  for (const e of events) {
    const data = e.data as { artifact?: { artifact_id?: unknown } } | undefined;
    const id = data?.artifact?.artifact_id;
    if (
      e.type === "artifact.delivered" &&
      typeof id === "string" &&
      !items.some((x) => x.id === id)
    )
      items.push({ id, name: deliveredName(e, id) });
  }
  return items;
}

/** Each delivered item, read only when asked for: the page shows the main one above. */
function DeliveredItems({
  api,
  worldId,
  items,
}: { api: Api; worldId: string; items: DeliveredFile[] }) {
  const [failed, setFailed] = useState(false);
  const readItem = (id: string, use: (blob: Blob) => void): void => {
    setFailed(false);
    readResult(api, worldId, id).then(use, () => setFailed(true));
  };
  return (
    <details data-testid="working-files">
      <summary>{`Working files (${items.length})`}</summary>
      <ul>
        {items.map(({ id, name }) => (
          <li key={id} className="park-world-resultactions">
            <span className="park-world-sub">{name}</span>
            <Button variant="secondary" size="sm" onClick={() => readItem(id, openResult)}>
              {`Open working file: ${name}`}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => readItem(id, (blob) => saveResult(blob, name))}
            >
              {`Download working file: ${name}`}
            </Button>
          </li>
        ))}
      </ul>
      {failed ? (
        <p className="park-world-noruns" role="alert">
          That item could not be loaded. Nothing is lost. Try opening or downloading it again.
        </p>
      ) : null}
    </details>
  );
}

/** The delivered result, read here; Open and Download are the same bytes the owner route serves (STUDIO-3: it sits
 * in the Result tab, where Share is the one filled button, so both are quiet). With several delivered items each is
 * listed with its own Open and Download (RESULT-LIVE). */
export function RunResult({
  api,
  worldId,
  events,
  shared,
  onAskQuestion,
  onChangeDirection,
}: {
  api: Api;
  worldId: string;
  events: readonly RunEvent[];
  /** The page's one read of the result (WORLD-LIVE), also used by the Delivery Dock. */
  shared: SharedResult;
  onAskQuestion?: () => void;
  onChangeDirection?: (instruction: string) => Promise<void>;
}) {
  return (
    <>
      <BrowserSteps events={events} />
      <ResultTab
        api={api}
        worldId={worldId}
        events={events}
        shared={shared}
        {...(onAskQuestion ? { onAskQuestion } : {})}
        {...(onChangeDirection ? { onChangeDirection } : {})}
      />
    </>
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

/** The one status banner: the progress line and bar, and a stopped run's recorded reason with "Try again". The
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
      {view.phase === "paused" && again ? (
        <div className="park-world-failed" data-testid="run-paused">
          <h2 className="park-world-h2">This run is paused</h2>
          <p className="park-world-noruns">
            Continue starts a new run using this task and its recorded progress.
          </p>
          <StartItAgain again={again} events={events} paused />
        </div>
      ) : null}
    </section>
  );
}
