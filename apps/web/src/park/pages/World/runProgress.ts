// UI-10 B8: what the World page says about a real run, derived from its recorded events alone (HR-1, HR-5):
// nothing here is estimated, and an event type the registry does not know changes nothing.
import type { RunEvent } from "./useRunEvents";

/** The words for the run's latest recorded world.* event; "Getting ready" until one says otherwise. */
const STATUS_OF: Readonly<Record<string, string>> = {
  "world.started": "Working",
  "world.resumed": "Working",
  "world.paused": "Paused",
  "world.completed": "Done",
  "world.failed": "Stopped with an error",
};

export interface RunProgress {
  readonly status: string;
  readonly credits: number;
  readonly waiting: number;
  readonly agents: number;
  readonly buildings: { readonly planned: number; readonly done: number };
  /** The latest recorded steps, newest last: the event's own summary and its recorded time of day (UTC). */
  readonly steps: readonly { readonly seq: number; readonly at: string; readonly text: string }[];
}

const STEPS_SHOWN = 6;
// The recorded time of day (UTC) straight from the ISO timestamp: no clock is read.
const clock = (ts: string): string => /^\d{4}-\d\d-\d\dT(\d\d:\d\d)/.exec(ts)?.[1] ?? "";

export function runProgress(all: readonly RunEvent[]): RunProgress {
  const events = all;
  let status = "Getting ready";
  for (const e of events) status = STATUS_OF[e.type] ?? status;
  const count = (type: string): number => events.filter((e) => e.type === type).length;
  const credits = Math.round(events.reduce((sum, e) => sum + e.credits, 0) * 10) / 10;
  return {
    status,
    credits,
    waiting: Math.max(0, count("approval.requested") - count("approval.resolved")),
    agents: count("agent.spawned"),
    buildings: { planned: count("building.planned"), done: count("building.completed") },
    steps: events
      .filter((e) => typeof e.summary === "string" && e.summary.trim() !== "")
      .slice(-STEPS_SHOWN)
      .map((e) => ({ seq: e.seq, at: clock(e.ts), text: e.summary })),
  };
}
