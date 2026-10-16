import { type ReactNode, useEffect, useRef, useState } from "react";
import { Buddy, ErrorState, LoadingState, useLoopPaused } from "../../design/tilo-t";

/** An approval reply proves this id exists; it does not prove that planning has finished. */
const pending = new Set<string>();

export function markPendingWorld(worldId: string): void {
  if (worldId) pending.add(worldId);
}

export const pendingWorld = (worldId: string): boolean => pending.has(worldId);

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
  const [error, setError] = useState(false);
  const loopRef = useRef<HTMLDivElement>(null);
  const paused = useLoopPaused(loopRef);
  const planned = phase === "planned";
  const failed = error || client === null;
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
          pending.delete(worldId);
          setPhase("planned");
        }
      },
      () => setError(true),
    );
  }, [client, planned, worldId]);

  if (planned) return <div className="park-world-enter">{children}</div>;
  return (
    <section className="park-pending-world" data-testid="pending-world">
      <h1 tabIndex={-1}>{failed ? "We can't open this world yet" : "Tilo is planning your world"}</h1>
      {failed ? (
        <ErrorState
          title="World updates are unavailable"
          body="You can return to your worlds and try again."
        />
      ) : (
        <div ref={loopRef} className={paused}>
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
