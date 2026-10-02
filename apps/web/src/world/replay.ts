// FR-WLD-08 / PRD 9.4 HR-4: replay and scrub of a finished run. The scrub point is display state
// (which moment of the recorded run the person is looking at): it records nothing, is never an
// event and moves nothing by itself (HR-1, HR-3). It is held per world, so World, Story, Trace and
// Inspect all show the same moment, and `null` means "the latest": the whole run.
//
// A scrubber has one stop per event: index 0 is before the first event, index i is just after the
// i-th. A stop is addressed by the seq of its last event (0 for the start).
import type { Event } from "@tilo/contracts";
import { useMemo, useSyncExternalStore } from "react";
import type { TiloClient } from "../api/client";
import { elapsed, useRunLog } from "./runLog";

const points = new Map<string, number>();
const listeners = new Set<() => void>();

export const getReplayPoint = (worldId: string): number | null => points.get(worldId) ?? null;

export function subscribeReplay(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

/** Moves this world's replay point (null: the latest). The same point again changes nothing. */
export function setReplayPoint(worldId: string, seq: number | null): void {
  if (getReplayPoint(worldId) === seq) return;
  if (seq === null) points.delete(worldId);
  else points.set(worldId, seq);
  for (const listener of [...listeners]) listener();
}

/** The seq a stop stands for: 0 for the start, else the seq of the event it follows. */
export function indexToPoint(events: readonly Event[], index: number): number {
  return index <= 0 ? 0 : (events[Math.min(index, events.length) - 1]?.seq ?? 0);
}

/** The stop a point falls on: the number of events at or before it (null: the last stop). */
export function pointToIndex(events: readonly Event[], point: number | null): number {
  if (point === null) return events.length;
  let lo = 0;
  let hi = events.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((events[mid] as Event).seq <= point) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The events a screen shows at this point: the whole run for null, else those up to the point. */
export function eventsUpTo(events: readonly Event[], point: number | null): readonly Event[] {
  return point === null ? events : events.slice(0, pointToIndex(events, point));
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "29 Sep 2026" in UTC, so every viewer reads the same day (and no ICU build can spell it "Sept"). */
const recordedDate = (ts: string): string => {
  const d = new Date(ts);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};

/** HR-4: "Replay of run #… recorded <date>". A dev fixture says what it is (BQ-07). Null while
 * there is no recorded event to name a run. */
export function replayBanner(events: readonly Event[], fixture: boolean): string | null {
  const first = events[0];
  if (!first) return null;
  const text = `Replay of run #${first.run_id} recorded ${recordedDate(first.ts)}`;
  return fixture ? `${text} · dev fixture, not a real run` : text;
}

/** What a stop says, for the screen and for assistive technology: event, seq, recorded time. */
export function scrubText(events: readonly Event[], index: number): string {
  const event = events[index - 1];
  if (!event) return "Start of the run, before the first event";
  return `Event ${index} of ${events.length}, seq ${event.seq}, ${elapsed(events, event)} into the run: ${event.type}`;
}

/** The world's replay point, for the controls. */
export function useReplayPoint(worldId: string): number | null {
  return useSyncExternalStore(subscribeReplay, () => getReplayPoint(worldId));
}

/** A world's recorded events as the screens show them at its replay point (all of them while
 * there is none). */
export function useReplayedLog(client: TiloClient, worldId: string) {
  const all = useRunLog(client, worldId);
  const point = useReplayPoint(worldId);
  return { events: useMemo(() => eventsUpTo(all, point), [all, point]) };
}
