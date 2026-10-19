// UI-10 B8: the recorded events of one world, as the client's subscription delivers them (GET /worlds/{id}/events,
// polled by the HTTP client). In seq order, a repeat ignored; none, and no subscription, for no client or no world.
import { useEffect, useState } from "react";

/** The part of a recorded event the page reads. */
export interface RunEvent {
  readonly seq: number;
  readonly type: string;
  readonly ts: string;
  readonly credits: number;
  readonly summary: string;
  readonly target?: string;
  readonly actor?: string;
  readonly district?: string | null;
  readonly data?: unknown;
}

/** What the page needs of the world client: the event subscription. */
export interface RunEventFeed {
  subscribeEvents(worldId: string, onEvent: (event: RunEvent) => void): () => void;
}

export function useRunEvents(
  source: RunEventFeed | null,
  worldId: string | null,
): readonly RunEvent[] {
  const [events, setEvents] = useState<readonly RunEvent[]>([]);
  useEffect(() => {
    setEvents([]);
    if (source === null || worldId === null) return undefined;
    return source.subscribeEvents(worldId, (event) => {
      setEvents((have) => {
        const last = have[have.length - 1];
        return last && event.seq <= last.seq ? have : [...have, event];
      });
    });
  }, [source, worldId]);
  return events;
}
