import { type ReactNode, useEffect, useRef, useState } from "react";
import { Buddy, ErrorState, LoadingState, useLoopPaused } from "../../design/tilo-t";

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
    onEvent: (event: { readonly type: string }) => void,
    onError?: (error: { readonly message: string }) => void,
  ): () => void;
}

/** The server's start response gives an id; only streamed events advance the visual story. */
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
  const goal = pendingWorldGoal(worldId);
  const [error, setError] = useState(false);
  const [worldFailed, setWorldFailed] = useState(false);
  const loopRef = useRef<HTMLDivElement>(null);
  const paused = useLoopPaused(loopRef);
  const planned = phase === "planned";
  const failed = error || worldFailed || client === null;
  useEffect(() => {
    if (planned || client === null) return undefined;
    return client.subscribeEvents(
      worldId,
      (event) => {
        if (event.type === "world.started") {
          // triggeredBy: world.started. The pool appears only after this recorded event.
          setPhase((current) => current === "planned" ? current : "started");
        }
        if (event.type === "world.planned") {
          // triggeredBy: world.planned. Enter the actual World only after its plan is recorded.
          clearPendingWorld(worldId);
          setPhase("planned");
        }
        if (event.type === "world.failed") {
          clearPendingWorld(worldId);
          setWorldFailed(true);
        }
      },
      () => setError(true),
    );
  }, [client, planned, worldId]);

  if (planned) return <div className="park-world-enter">{children}</div>;
  return (
    <section className="park-pending-world" data-testid="pending-world">
      <h1 tabIndex={-1}>{worldFailed ? "This world stopped" : failed ? "We can't open this world yet" : "Tilo is planning your world"}</h1>
      {failed ? (
        <ErrorState
          title={worldFailed ? "This world stopped" : "World updates are unavailable"}
          body={worldFailed ? "Return to your worlds to see what happened." : "You can return to your worlds and try again."}
        />
      ) : (
        <div ref={loopRef} className={paused}>
          {phase === "waiting" && goal ? (
            <div className="park-pending-world__blueprint" data-testid="run-blueprint">
              BLUEPRINT · {goal}
            </div>
          ) : null}
          {phase === "started" ? (
            <div className="park-pending-world__pool" aria-hidden="true">
              <Buddy mood="swim" size={96} />
            </div>
          ) : null}
          <LoadingState
            layout="world"
            caption={phase === "started" ? "world.started · Waiting for world.planned" : "Waiting for world.started"}
          />
        </div>
      )}
      <a href="/worlds">Your worlds</a>
    </section>
  );
}
