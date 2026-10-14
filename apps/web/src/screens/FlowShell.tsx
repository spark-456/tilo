// PRD 18.3 flow screen S-04 (the live stage's summary and one primary button); S-01 to S-03 are the Park Home's
// one-step start now (OLD-UI-OUT wave 1). This file also holds Loaded/Primary/Summary for the screens still kept. S-12 (Delivery) is S_12.tsx, routed by routes.tsx.
// Every client call has loading, empty and error states with a retry (PRD 18.4); one filled
// primary button per screen (UX-1).
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useClient } from "../api/ClientProvider";
import { LifetimeCapDialog } from "../components/LifetimeCapDialog";
import { ReplayBanner } from "../components/ReplayBanner";
import { useFlowRoute } from "../router";
import "./flow/flow.css";
import { type Action, type Remote, useAction } from "./remote";

const enc = encodeURIComponent;

/** What each flow screen calls itself. Only the live stage is left (OLD-UI-OUT wave 1 retired S-01 to S-03). */
const HEADINGS: Readonly<Record<string, string>> = {};

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

export function FlowShell() {
  const { route } = useFlowRoute();
  const heading = useRef<HTMLHeadingElement>(null);
  const id = "worldId" in route ? route.worldId : "";
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
        return null; // not an address of the old app: Root sends the retired intake addresses to Park Home
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
      className="flow-shell"
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
