// TILO-T-WORLD test support: a minimal TiloClient for the live World overlays (hover card, panel, chat, team meeting).
// It serves one layout and a growing list of events, exactly the two things the overlays read; every other method is
// absent, so a component reaching for anything else fails loudly. Not bundled.
import type { Event, Layout } from "@tilo/contracts";
import type { ReactNode } from "react";
import { ClientProvider } from "../src/api/ClientProvider";
import type { TiloClient } from "../src/api/client";

export interface FakeWorld {
  readonly client: TiloClient;
  /** Delivers one more recorded event to every subscriber, as the run's event poll would. */
  push(event: Event): void;
}

export function fakeWorld(layout: Layout, initial: readonly Event[] = []): FakeWorld {
  const events = [...initial];
  const listeners = new Set<(e: Event) => void>();
  const client = {
    getLayout: async () => layout,
    subscribeEvents: (_world: string, onEvent: (e: Event) => void) => {
      for (const e of events) onEvent(e);
      listeners.add(onEvent);
      return () => listeners.delete(onEvent);
    },
  } as unknown as TiloClient;
  return {
    client,
    push(event) {
      events.push(event);
      for (const l of [...listeners]) l(event);
    },
  };
}

export const withClient = (client: TiloClient, children: ReactNode) => (
  <ClientProvider client={client}>{children}</ClientProvider>
);

let n = 0;
/** One recorded event with the envelope filled in; `seq` counts up across a test file (call `resetEvents` first). */
export function ev(
  type: string,
  actor: string,
  target: string,
  data: object = {},
  more: Partial<Event> = {},
): Event {
  n += 1;
  return {
    v: "1.0",
    id: `01JB5VQ${String(n).padStart(19, "0")}`,
    seq: n,
    ts: `2026-10-16T09:${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}.000Z`,
    world_id: "w_live",
    run_id: "r_live",
    type,
    actor,
    target,
    level: "L1",
    district: "D1",
    item: null,
    severity: "info",
    credits: 0,
    summary: `${type} summary`,
    cause: null,
    vis: "all",
    authz: null,
    data,
    trace: {},
    ...more,
  } as unknown as Event;
}
export const resetEvents = (): void => {
  n = 0;
};
