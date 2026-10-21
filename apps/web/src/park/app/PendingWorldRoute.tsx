import { type ReactNode, useEffect, useState } from "react";
import { PoolLoader, type PoolLoaderEvent } from "../shared/tiloT";

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

/** The first recorded sign that agents are working: nothing is pending any more, whatever came before it. */
const WORK_EVENT = /^(agent|building|unit|artifact|question|approval)\./;

/**
 * UX-SMOOTH (owner, 21 Oct: "the world generation stays stuck on the loading screen for too long and by the time we
 * load in, everything is already complete"): the World page opens the moment Start answers. Nothing covers it. While
 * the server's reply is all there is (the Director is still planning; `world.planned` and `world.started` are written
 * together when the plan is done), one compact card on the page says so, with the task's own words, until the plan,
 * the first work or a stop is recorded. The page itself shows the recorded events as they arrive.
 */
export function PendingWorldRoute({
  worldId,
  client,
  children,
}: {
  readonly worldId: string;
  readonly client: EventFeed | null;
  readonly children: ReactNode;
}) {
  const [planned, setPlanned] = useState(() => !pendingWorld(worldId));
  const [events, setEvents] = useState<PoolLoaderEvent[]>([]);
  const goal = pendingWorldGoal(worldId);
  const [error, setError] = useState(false);
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
        // triggeredBy: world.planned, world.failed or the first recorded work. The card goes; the page stays.
        if (
          event.type === "world.planned" ||
          event.type === "world.failed" ||
          WORK_EVENT.test(event.type)
        ) {
          clearPendingWorld(worldId);
          setPlanned(true);
        }
      },
      () => setError(true),
    );
  }, [client, planned, worldId]);

  const unavailable = !planned && (error || client === null);
  return (
    <PoolLoader
      kind="task"
      events={planned ? [] : events}
      pending={!planned && !unavailable}
      goal={planned ? undefined : goal}
    >
      {unavailable ? (
        <output className="park-pending-world__note">
          World updates are unavailable. Return to your worlds and try again.
        </output>
      ) : null}
      <div className="park-world-enter">{children}</div>
    </PoolLoader>
  );
}
