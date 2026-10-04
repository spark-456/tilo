// The recorded events of one world as the Story, Trace, Inspect and HUD screens read them (AGW-08).
// One subscription per client and world is kept for the page's lifetime, so moving between lenses
// never restarts the replay. Events apply in seq order and a repeat is ignored (the reducer's
// rule, FR-WLD-04). Everything the screens show is derived from these events (HR-1, HR-5).
import type { Event } from "@tilo/contracts";
import { useSyncExternalStore } from "react";
import type { TiloClient } from "../api/client";
import { eventsUpTo, getReplayPoint, subscribeReplay } from "./replayPoint";
import { type RunStatus, worldStatus } from "./runSummary";

interface Run {
  events: readonly Event[];
  readonly listeners: Set<() => void>;
}

const EMPTY: readonly Event[] = [];
const runs = new WeakMap<TiloClient, Map<string, Run>>();

function runFor(client: TiloClient, worldId: string): Run {
  const byWorld = runs.get(client) ?? new Map<string, Run>();
  runs.set(client, byWorld);
  const existing = byWorld.get(worldId);
  if (existing) return existing;
  const run: Run = { events: EMPTY, listeners: new Set() };
  byWorld.set(worldId, run);
  client.subscribeEvents(worldId, (event) => {
    const last = run.events[run.events.length - 1];
    if (last && event.seq <= last.seq) return;
    run.events = [...run.events, event];
    for (const listener of run.listeners) listener();
  });
  return run;
}

/** Every event received so far for the world, in seq order. */
export function useRunLog(client: TiloClient, worldId: string): readonly Event[] {
  return useSyncExternalStore(
    (onChange) => {
      const run = runFor(client, worldId);
      run.listeners.add(onChange);
      return () => run.listeners.delete(onChange);
    },
    () => runs.get(client)?.get(worldId)?.events ?? EMPTY,
  );
}

/** Hands `onEvent` every event of the world already received, then each one as it arrives, in seq
 * order, once each (the stage's live feed shares the page's one subscription). Returns a stop. */
export function followRun(
  client: TiloClient,
  worldId: string,
  onEvent: (event: Event) => void,
): () => void {
  const run = runFor(client, worldId);
  let last = 0;
  const flush = () => {
    for (const event of run.events) {
      if (event.seq <= last) continue;
      last = event.seq;
      onEvent(event);
    }
  };
  run.listeners.add(flush);
  flush();
  return () => run.listeners.delete(flush);
}

/** The run's recorded status (FR-WLD-07: the stage veil follows it); "idle" with no world. Only
 * re-renders when the status word changes, not on every event. */
export function useRunStatus(client: TiloClient, worldId: string | null): RunStatus {
  return useSyncExternalStore(
    (onChange) => {
      if (worldId === null) return () => undefined;
      const run = runFor(client, worldId);
      run.listeners.add(onChange);
      const unreplay = subscribeReplay(onChange);
      return () => {
        run.listeners.delete(onChange);
        unreplay();
      };
    },
    // FR-WLD-08: at a scrubbed moment the status is the one recorded by then, so the veil never
    // claims a pause the run had not reached (HR-1).
    () =>
      worldId === null
        ? worldStatus(EMPTY)
        : worldStatus(
            eventsUpTo(runs.get(client)?.get(worldId)?.events ?? EMPTY, getReplayPoint(worldId)),
          ),
  );
}

/** Credits spent so far: the sum of what the events record, never an estimate. */
export const creditsUsed = (events: readonly Event[]): number =>
  Math.round(events.reduce((sum, e) => sum + e.credits, 0) * 10) / 10;

/** Approvals asked for and not yet answered, from approval.requested and approval.resolved. */
export const waitingForYou = (events: readonly Event[]): number =>
  Math.max(
    0,
    events.filter((e) => e.type === "approval.requested").length -
      events.filter((e) => e.type === "approval.resolved").length,
  );

/** "m:ss" since the first event: the recorded gap, not the wall clock. */
export function elapsed(events: readonly Event[], event: Event): string {
  const first = events[0];
  const s = Math.max(
    0,
    Math.round((Date.parse(event.ts) - Date.parse(first?.ts ?? event.ts)) / 1000),
  );
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
