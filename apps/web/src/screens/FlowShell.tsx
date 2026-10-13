// PRD 18.3 flow screens S-01, S-02, S-03 and S-04 as placeholders (heading, one primary button to
// the next step) that AGW-02 to AGW-05 fill in. S-12 (Delivery) is S_12.tsx, routed by routes.tsx.
// Every client call has loading, empty and error states with a retry (PRD 18.4); one filled
// primary button per screen (UX-1).
import { type ReactNode, Suspense, lazy, useEffect, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { LifetimeCapDialog } from "../components/LifetimeCapDialog";
import { ReplayBanner } from "../components/ReplayBanner";
import { useFlowRoute } from "../router";
import { ChunkBoundary } from "./ChunkBoundary";
import { StartScreen } from "./flow/StartScreen";
import "./flow/flow.css";
import { type Action, type Remote, useAction } from "./remote";

const enc = encodeURIComponent;

// S-02 and S-03 load when a task reaches them (NFR-01): the Start screen does not carry their code.
const Understanding = lazy(() =>
  import("./s02/Understanding").then((m) => ({ default: m.Understanding })),
);
const Approaches = lazy(() => import("./s03/Approaches").then((m) => ({ default: m.Approaches })));

/** What each flow screen calls itself. Start is the Home hero (artboard Tilo Home v2). */
const HEADINGS: Readonly<Record<string, string>> = { Start: "What should Tilo do?" };

function Notice({ message, onRetry }: { message: string; onRetry?: (() => void) | undefined }) {
  return (
    <div className="flow-notice" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button type="button" className="secondary" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  );
}

/** SEC-16: the lifetime-allowance pop-up in the place of the generic error. Close hides it; `rearm` changing (the next
 * try starts) lets the next failure show it again. Its feedback goes through the client (nothing says Thanks early). */
function CapDialog({ rearm }: { rearm: unknown }) {
  const client = useClient();
  const [closed, setClosed] = useState(false);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `rearm` is the trigger, not a value read here.
  useEffect(() => setClosed(false), [rearm]);
  if (closed) return null;
  return (
    <LifetimeCapDialog
      submit={(words) => client.submitFeedback(words)}
      onClose={() => setClosed(true)}
    />
  );
}

export function Summary({ children }: { children: ReactNode }) {
  return <p className="flow-summary">{children}</p>;
}

/** The loading, error and empty states of one remote value; `children` renders the ready one.
 * All four states sit in one `flow-slot` with a reserved height, so data arriving (UX-1, CLS)
 * never moves what is below. */
export function Loaded<T>({
  what,
  remote,
  retry,
  isEmpty,
  empty,
  children,
}: {
  what: string;
  remote: Remote<T>;
  /** Omit it when a retry cannot change the outcome (the data is already in memory). */
  retry?: (() => void) | undefined;
  isEmpty: (value: T) => boolean;
  /** Replaces the generic empty notice, for an empty state that has its own next step. */
  empty?: ReactNode;
  children: (value: T) => ReactNode;
}) {
  let body: ReactNode;
  if (remote.status === "loading") {
    body = <output className="flow-loading">Loading {what}…</output>;
  } else if (remote.status === "error" && remote.replayOnly) {
    body = <ReplayBanner />; // NFR-22: the label replaces the generic error, in the same slot
  } else if (remote.status === "error" && remote.lifetimeCap) {
    body = <CapDialog rearm={remote} />; // SEC-16: the allowance pop-up replaces it too
  } else if (remote.status === "error") {
    body = <Notice message={remote.message} onRetry={retry} />;
  } else if (isEmpty(remote.value)) {
    body = empty ? (
      <div className="flow-notice" role="alert">
        {empty}
      </div>
    ) : (
      <Notice message={`Nothing came back for ${what}. You can try again.`} onRetry={retry} />
    );
  } else {
    body = children(remote.value);
  }
  return <div className="flow-slot">{body}</div>;
}

export function Primary({
  label,
  action,
  disabled = false,
}: { label: string; action: Action; disabled?: boolean }) {
  return (
    <>
      {action.replayOnly ? (
        <ReplayBanner />
      ) : action.lifetimeCap ? (
        <CapDialog rearm={action.busy} />
      ) : (
        action.error && <Notice message={action.error} onRetry={action.go} />
      )}
      <button
        type="button"
        className="primary"
        disabled={disabled}
        aria-busy={action.busy ? "true" : undefined}
        onClick={action.go}
      >
        {action.busy ? `${label}…` : label}
      </button>
    </>
  );
}

function World({ worldId }: { worldId: string }) {
  const action = useAction("open the delivery", async () => `/world/${enc(worldId)}/delivery`);
  return <Primary label="View delivery" action={action} />;
}

/** A screen whose chunk loads on demand: the card is already drawn, so the words sit in its slot. */
function Later({ children }: { children: ReactNode }) {
  return (
    <ChunkBoundary>
      <Suspense
        fallback={
          <div className="flow-slot">
            <output className="flow-loading">Loading…</output>
          </div>
        }
      >
        {children}
      </Suspense>
    </ChunkBoundary>
  );
}

export function FlowShell() {
  const { route } = useFlowRoute();
  const heading = useRef<HTMLHeadingElement>(null);
  const id = "taskId" in route ? route.taskId : "worldId" in route ? route.worldId : "";
  const key = `${route.screen}:${id}`;
  const shownKey = useRef(key);
  // After a route change, focus moves to the new screen's heading, so keyboard and
  // screen-reader users keep their place.
  useEffect(() => {
    if (shownKey.current === key) return; // the first render, and StrictMode's second effect run
    shownKey.current = key;
    heading.current?.focus();
  }, [key]);
  // Screens that load data show their summary only once it is ready (see Loaded's children).
  const screen = (() => {
    switch (route.screen) {
      case "Start":
        return <StartScreen />;
      case "Understanding":
        return (
          <Later>
            <Understanding taskId={route.taskId} />
          </Later>
        );
      case "Approaches":
        return (
          <Later>
            <Approaches taskId={route.taskId} />
          </Later>
        );
      case "World":
        return (
          <>
            <Summary>Watch the run here as it happens.</Summary>
            <World worldId={route.worldId} />
          </>
        );
    }
  })();
  return (
    <section
      className={route.screen === "Start" ? "flow-shell flow-wide" : "flow-shell"}
      data-testid="flow-shell"
      data-screen={route.screen}
      aria-label="Task flow"
    >
      <h1 className="flow-heading" ref={heading} tabIndex={-1}>
        {HEADINGS[route.screen] ?? route.screen}
      </h1>
      <div key={key}>{screen}</div>
    </section>
  );
}
