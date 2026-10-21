// UX-SMOOTH: the World page reads a run's events through the same one-per-world subscription the live stage uses
// (world/runLog: shared, closed shortly after the last reader leaves). Before, the page and the stage each polled
// GET /worlds/{id}/events and each first downloaded the whole stream.
import type { TiloClient } from "../../api/client";
import { watchRun } from "../../world/runLog";

/** What a reader needs of the world client: its events subscription. */
export interface EventSource<E> {
  subscribeEvents(worldId: string, onEvent: (event: E) => void): () => void;
}

/** Every event the world's shared subscription holds so far, then each new one, in seq order. Returns stop. */
export function watchWorldEvents<E>(
  source: EventSource<E>,
  worldId: string,
  onEvent: (event: E) => void,
): () => void {
  // runLog keys its subscriptions by the client object and only calls its subscribeEvents.
  return watchRun(source as unknown as TiloClient, worldId, (event) =>
    onEvent(event as unknown as E),
  );
}
