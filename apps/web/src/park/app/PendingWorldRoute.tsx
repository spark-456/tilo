import { type ReactNode, useEffect, useState } from "react";

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

/** Holds the new world's route until its real event feed says that a plan or run exists. */
export function PendingWorldRoute({
  worldId,
  client,
  children,
}: {
  readonly worldId: string;
  readonly client: EventFeed | null;
  readonly children: ReactNode;
}) {
  const [waiting, setWaiting] = useState(() => pendingWorld(worldId));
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!waiting || client === null) return undefined;
    return client.subscribeEvents(
      worldId,
      (event) => {
        if (event.type !== "world.planned" && event.type !== "world.started") return;
        pending.delete(worldId);
        setWaiting(false);
      },
      () => setError(true),
    );
  }, [client, waiting, worldId]);

  if (!waiting) return <>{children}</>;
  return (
    <section className="park-pending-world" data-testid="pending-world" aria-live="polite">
      <h1 tabIndex={-1}>Tilo is planning your world</h1>
      <p>
        {error
          ? "World updates are unavailable right now. You can return to your worlds and try again."
          : "Your world will open when its plan or start is recorded."}
      </p>
      <a href="/worlds">Your worlds</a>
    </section>
  );
}
