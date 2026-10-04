// PRD 18.3 flow screens S-01, S-02, S-03 and S-04 as placeholders (heading, one primary button to
// the next step) that AGW-02 to AGW-05 fill in. S-12 (Delivery) is S_12.tsx, routed by routes.tsx.
// Every client call has loading, empty and error states with a retry (PRD 18.4); one filled
// primary button per screen (UX-1).
import { type ReactNode, useEffect, useRef } from "react";
import { useFlowRoute } from "../router";
import { StartScreen } from "./flow/StartScreen";
import "./flow/flow.css";
import { type Action, type Remote, useAction } from "./remote";
import { Understanding } from "./s02/Understanding";
import { Approaches } from "./s03/Approaches";

const enc = encodeURIComponent;

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
      {action.error && <Notice message={action.error} onRetry={action.go} />}
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
        return <Understanding taskId={route.taskId} />;
      case "Approaches":
        return <Approaches taskId={route.taskId} />;
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
        {route.screen}
      </h1>
      <div key={key}>{screen}</div>
    </section>
  );
}
