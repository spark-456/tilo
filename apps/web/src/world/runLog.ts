// The recorded events of one world as the Story, Trace, Inspect and HUD screens read them (AGW-08).
// One subscription per client and world is shared by everything that reads the world and is closed
// shortly after the last reader leaves (#294: a world nobody shows is not polled), so moving between
// lenses never restarts the replay. Events apply in seq order and a repeat is ignored (the reducer's
// rule, FR-WLD-04). Everything the screens show is derived from these events (HR-1, HR-5).
import type { Event } from "@tilo/contracts";
import { useSyncExternalStore } from "react";
import type { TiloClient } from "../api/client";
import { eventsUpTo, getReplayPoint, subscribeReplay } from "./replayPoint";
import { type RunStatus, worldStatus } from "./runSummary";

interface Run {
  events: readonly Event[];
  readonly listeners: Set<() => void>;
  /** Closes the run's events subscription. */
  stop: () => void;
  /** The pending close after the last reader left; a reader arriving first cancels it. */
  closing: ReturnType<typeof setTimeout> | undefined;
}

/** How long a world with no reader keeps its subscription. A lens switch unmounts one screen and
 * mounts the next within a frame or two, so it never reaches this; leaving the world does. */
export const CLOSE_AFTER_MS = 1500;

const EMPTY: readonly Event[] = [];
const runs = new WeakMap<TiloClient, Map<string, Run>>();

function runFor(client: TiloClient, worldId: string): Run {
  const byWorld = runs.get(client) ?? new Map<string, Run>();
  runs.set(client, byWorld);
  const existing = byWorld.get(worldId);
  if (existing) return existing;
  const run: Run = {
    events: EMPTY,
    listeners: new Set(),
    stop: () => undefined,
    closing: undefined,
  };
  byWorld.set(worldId, run);
  run.stop = client.subscribeEvents(worldId, (event) => {
    const last = run.events[run.events.length - 1];
    if (last && event.seq <= last.seq) return;
    run.events = [...run.events, event];
    for (const listener of run.listeners) listener();
  });
  return run;
}

/** Adds `listener` to the world's run, starting its subscription if no one holds it. Returns the
 * release: when the last listener has let go for CLOSE_AFTER_MS the subscription stops and the
 * run is forgotten, so the next visit reads the world afresh. */
function hold(
  client: TiloClient,
  worldId: string,
  listener: () => void,
): { run: Run; release: () => void } {
  const run = runFor(client, worldId);
  clearTimeout(run.closing);
  run.closing = undefined;
  run.listeners.add(listener);
  const release = () => {
    run.listeners.delete(listener);
    if (run.listeners.size > 0 || run.closing !== undefined) return;
    run.closing = setTimeout(() => {
      run.closing = undefined;
      if (run.listeners.size > 0) return;
      run.stop();
      const byWorld = runs.get(client);
      if (byWorld?.get(worldId) === run) byWorld.delete(worldId);
    }, CLOSE_AFTER_MS);
  };
  return { run, release };
}

/** Hands `onEvent` every event the run holds so far, at once and in seq order, then each new one
 * as it arrives, once each in seq order (the stage draws the run the lenses and the HUD read,
 * sharing the page's one subscription). Returns stop. */
export function watchRun(
  client: TiloClient,
  worldId: string,
  onEvent: (event: Event) => void,
): () => void {
  let delivered = 0;
  const flush = () => {
    for (; delivered < held.run.events.length; delivered++)
      onEvent(held.run.events[delivered] as Event);
  };
  const held = hold(client, worldId, flush);
  flush();
  return held.release;
}

/** Every event received so far for the world, in seq order (none, and no subscription, for null). */
export function useRunLog(client: TiloClient, worldId: string | null): readonly Event[] {
  return useSyncExternalStore(
    (onChange) => {
      if (worldId === null) return () => undefined; // no run: nothing is subscribed
      return hold(client, worldId, onChange).release;
    },
    () => (worldId === null ? EMPTY : (runs.get(client)?.get(worldId)?.events ?? EMPTY)),
  );
}

/** The run's recorded status (FR-WLD-07: the stage veil follows it); "idle" with no world. Only
 * re-renders when the status word changes, not on every event. */
export function useRunStatus(client: TiloClient, worldId: string | null): RunStatus {
  return useSyncExternalStore(
    (onChange) => {
      if (worldId === null) return () => undefined;
      const { release } = hold(client, worldId, onChange);
      const unreplay = subscribeReplay(onChange);
      return () => {
        release();
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
