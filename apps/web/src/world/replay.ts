// FR-WLD-08 / PRD 9.4 HR-4: replay and scrub of a finished run. The replay point and the stops it
// falls on live in replayPoint.ts (re-exported here); this module words them for the screen and
// reads the run log through them.
import type { Event } from "@tilo/contracts";
import { useMemo, useSyncExternalStore } from "react";
import type { TiloClient } from "../api/client";
import { eventsUpTo, getReplayPoint, subscribeReplay } from "./replayPoint";
import { elapsed, useRunLog } from "./runLog";

export {
  eventsUpTo,
  getReplayPoint,
  indexToPoint,
  pointToIndex,
  setReplayPoint,
  subscribeReplay,
} from "./replayPoint";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "29 Sep 2026" in UTC, so every viewer reads the same day (and no ICU build can spell it "Sept");
 * null for a timestamp that is not a date, so a banner never states a wrong one. */
const recordedDate = (ts: string): string | null => {
  const d = new Date(ts);
  return Number.isNaN(d.getTime())
    ? null
    : `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};

/** HR-4: "Replay of run #… recorded <date>". A dev fixture says what it is (BQ-07). Null while
 * there is no recorded event to name a run; no date (rather than a wrong one) when the first
 * event's timestamp is not a date. */
export function replayBanner(events: readonly Event[], fixture: boolean): string | null {
  const first = events[0];
  if (!first) return null;
  const date = recordedDate(first.ts);
  const text = `Replay of run #${first.run_id}${date ? ` recorded ${date}` : ""}`;
  return fixture ? `${text} · dev fixture, not a real run` : text;
}

/** What a stop says, for the screen and for assistive technology: event, seq, recorded time. */
export function scrubText(events: readonly Event[], index: number): string {
  const event = events[index - 1];
  if (!event) return "Start of the run, before the first event";
  const time = Number.isNaN(Date.parse(event.ts)) ? "" : `, ${elapsed(events, event)} into the run`;
  return `Event ${index} of ${events.length}, seq ${event.seq}${time}: ${event.type}`;
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
