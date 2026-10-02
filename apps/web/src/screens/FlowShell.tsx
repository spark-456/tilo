// PRD 18.3 flow screens S-01, S-02, S-03, S-04 and S-12 as placeholders (heading, one primary
// button to the next step) that AGW-02 to AGW-05 fill in. Every client call has loading, empty
// and error states with a retry (PRD 18.4); one filled primary button per screen (UX-1).
import { type ReactNode, useEffect, useRef } from "react";
import { useClient } from "../api/ClientProvider";
import type { ApproachesResult } from "../api/client";
import { useFlowRoute } from "../router";
import { StartScreen } from "./flow/StartScreen";
import "./flow/flow.css";
import { type Action, type Remote, useAction, useRemote } from "./remote";

const enc = encodeURIComponent;

function Notice({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flow-notice" role="alert">
      <p>{message}</p>
      <button type="button" className="secondary" onClick={onRetry}>
        Try again
      </button>
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
  children,
}: {
  what: string;
  remote: Remote<T>;
  retry: () => void;
  isEmpty: (value: T) => boolean;
  children: (value: T) => ReactNode;
}) {
  let body: ReactNode;
  if (remote.status === "loading") {
    body = <output className="flow-loading">Loading {what}…</output>;
  } else if (remote.status === "error") {
    body = <Notice message={remote.message} onRetry={retry} />;
  } else if (isEmpty(remote.value)) {
    body = <Notice message={`Nothing came back for ${what}. You can try again.`} onRetry={retry} />;
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

function Understanding({ taskId }: { taskId: string }) {
  const client = useClient();
  const action = useAction("confirm the brief", async () => {
    await client.answerQuestions(taskId, [], {});
    return `/task/${enc(taskId)}/approaches`;
  });
  return <Primary label="Confirm understanding" action={action} />;
}

/** The recommended approach and its cap (its upper credit estimate), from getApproaches. */
async function loadRecommendation(getApproaches: Promise<ApproachesResult>) {
  const result = await getApproaches;
  const chosen = result.approaches.find((a) => a.id === result.recommended);
  if (result.approaches.length > 0 && !chosen) {
    throw new Error("the recommended approach is not in the list");
  }
  return { result, chosen };
}

function Approaches({ taskId }: { taskId: string }) {
  const client = useClient();
  const [remote, retry] = useRemote("load the approaches", () =>
    loadRecommendation(client.getApproaches(taskId)),
  );
  const ready = remote.status === "ready" ? remote.value : null;
  const action = useAction("start the run", async () => {
    if (!ready?.chosen) throw new Error("no approach is loaded");
    const { world_id } = await client.approve(taskId, {
      approach_id: ready.chosen.id,
      budget_cap: ready.chosen.credits.max,
    });
    return `/world/${enc(world_id)}`;
  });
  return (
    <>
      <Loaded
        what="the approaches"
        remote={remote}
        retry={retry}
        isEmpty={(v) => v.chosen === undefined}
      >
        {({ result, chosen }) => (
          <>
            <Summary>Compare priced approaches and confirm your budget cap.</Summary>
            <p className="flow-detail">
              Recommended: {chosen?.label}. This run can use up to {chosen?.credits.max} credits
              (about US${((chosen?.credits.max ?? 0) * result.credit_usd).toFixed(2)}). You can
              pause it any time.
            </p>
          </>
        )}
      </Loaded>
      <Primary label="Approve & start" action={action} disabled={!ready?.chosen} />
    </>
  );
}

function World({ worldId }: { worldId: string }) {
  const action = useAction("open the delivery", async () => `/world/${enc(worldId)}/delivery`);
  return <Primary label="View delivery" action={action} />;
}

function Delivery({ worldId }: { worldId: string }) {
  const client = useClient();
  const [remote, retry] = useRemote("load the delivery", () => client.getDelivery(worldId));
  const action = useAction("start a new task", async () => "/");
  return (
    <>
      <Loaded
        what="the delivery"
        remote={remote}
        retry={retry}
        isEmpty={(d) => d.artifacts.length === 0}
      >
        {(d) => (
          <>
            <Summary>Verified deliverables are ready at the Delivery Dock.</Summary>
            <p className="flow-detail">
              {d.artifacts.length} deliverable(s), {d.credits_used} credits used.
              {d.time_saved &&
                ` About ${d.time_saved.low_min} to ${d.time_saved.high_min} min saved (estimate).`}
            </p>
          </>
        )}
      </Loaded>
      <Primary label="New task" action={action} />
    </>
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
          <>
            <Summary>Review the extracted brief and clarifying questions.</Summary>
            <Understanding taskId={route.taskId} />
          </>
        );
      case "Approaches":
        return <Approaches taskId={route.taskId} />;
      case "World":
        return (
          <>
            <Summary>Watch the run here as it happens.</Summary>
            <World worldId={route.worldId} />
          </>
        );
      case "Delivery":
        return <Delivery worldId={route.worldId} />;
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
