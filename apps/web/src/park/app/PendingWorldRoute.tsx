import { type ReactNode, useEffect, useState } from "react";
import { ErrorState, LoadingState, PoolLoader, type PoolLoaderEvent } from "../shared/tiloT";

/** An approval reply proves this id exists; it does not prove that planning has finished. */
const pending = new Set<string>();
const pendingGoals = new Map<string, string>();

export function markPendingWorld(worldId: string, goal?: string): void {
  if (!worldId) return;
  pending.add(worldId);
  if (goal) pendingGoals.set(worldId, goal);
}

export const pendingWorld = (worldId: string): boolean => pending.has(worldId);
const pendingWorldGoal = (worldId: string): string | undefined => pendingGoals.get(worldId);

function clearPendingWorld(worldId: string): void {
  pending.delete(worldId);
  pendingGoals.delete(worldId);
}

interface EventFeed {
  subscribeEvents(
    worldId: string,
    onEvent: (event: { readonly type: string; readonly ts?: string }) => void,
    onError?: (error: { readonly message: string }) => void,
  ): () => void;
}

/** After `world.started`, the first recorded sign that agents are working. The live run records no `world.planned`
 * (the Director's plan is its layout, written before `world.started`), so a stage waiting for it alone never opened. */
const WORK_EVENT = /^(agent|building|unit|artifact|question|approval)\./;

/** The server's start response gives an id; only streamed events advance the visual story. The World page itself is
 * never covered: from `world.started` it is mounted and interactive, with a compact planning card on it until the
 * plan or the first work is recorded (b: the pool overlay used to block live worlds). */
export function PendingWorldRoute({
  worldId,
  client,
  children,
}: {
  readonly worldId: string;
  readonly client: EventFeed | null;
  readonly children: ReactNode;
}) {
  const [phase, setPhase] = useState<"waiting" | "started" | "planned">(() =>
    pendingWorld(worldId) ? "waiting" : "planned",
  );
  const [events, setEvents] = useState<PoolLoaderEvent[]>([]);
  const goal = pendingWorldGoal(worldId);
  const [error, setError] = useState(false);
  const [worldFailed, setWorldFailed] = useState(false);
  const planned = phase === "planned";
  const failed = (error || worldFailed || client === null) && phase === "waiting";
  useEffect(() => {
    if (planned || client === null) return undefined;
    return client.subscribeEvents(
      worldId,
      (event) => {
        if (
          event.type === "world.started" ||
          event.type === "world.planned" ||
          event.type === "world.failed"
        ) {
          setEvents((current) => {
            if (current.some((recorded) => recorded.type === event.type)) return current;
            const recorded = event.ts ? { type: event.type, ts: event.ts } : { type: event.type };
            return [...current, recorded];
          });
        }
        if (event.type === "world.started") {
          // triggeredBy: world.started. The World page mounts and the planning card appears after this recorded event.
          setPhase((current) => (current === "planned" ? current : "started"));
        }
        if (event.type === "world.planned") {
          // triggeredBy: world.planned. The planning card goes once the plan is recorded.
          clearPendingWorld(worldId);
          setPhase("planned");
        }
        if (WORK_EVENT.test(event.type)) {
          // triggeredBy: a recorded work event after world.started (agents are already running, so nothing is pending).
          setPhase((current) => {
            if (current !== "started") return current;
            clearPendingWorld(worldId);
            return "planned";
          });
        }
        if (event.type === "world.failed") {
          clearPendingWorld(worldId);
          setWorldFailed(true);
          // A run that had started keeps its World page, which names the stop and offers Start it again.
          setPhase((current) => (current === "started" ? "planned" : current));
        }
      },
      () => setError(true),
    );
  }, [client, planned, worldId]);

  return (
    // Once the route has left the pending state (plan or first work recorded) the card has nothing left to wait for.
    <PoolLoader kind="task" events={planned ? [] : events}>
      {phase !== "waiting" ? (
        <div className="park-world-enter">{children}</div>
      ) : (
        <section className="park-pending-world" data-testid="pending-world">
          <h1 tabIndex={-1}>
            {worldFailed
              ? "This world stopped"
              : failed
                ? "We can't open this world yet"
                : "Tilo is planning your world"}
          </h1>
          {failed ? (
            <ErrorState
              title={worldFailed ? "This world stopped" : "World updates are unavailable"}
              body={
                worldFailed
                  ? "Return to your worlds to see what happened."
                  : "You can return to your worlds and try again."
              }
            />
          ) : (
            <div>
              {goal ? (
                <div className="park-pending-world__blueprint" data-testid="run-blueprint">
                  BLUEPRINT · {goal}
                </div>
              ) : null}
              <LoadingState layout="world" caption="Waiting for world.started" />
            </div>
          )}
          <a href="/worlds">Your worlds</a>
        </section>
      )}
    </PoolLoader>
  );
}
