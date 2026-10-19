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

/** X-ORPHAN-1: the world's last word is the `world.failed` a restart wrote ("start it again"); no other stop is. */
export const RESTART_REASON = "Tilo restarted during this run; start it again";
export function isRestartStop(events: readonly RunEvent[]): boolean {
  const last = [...events].reverse().find((e) => e.type.startsWith("world."));
  if (last?.type !== "world.failed") return false;
  const data = last.data as { reason?: unknown } | null | undefined;
  return data?.reason === RESTART_REASON;
}

/** The same last grant the rerun API reuses, and outbound activity actually recorded before the stop. */
export function restartApproval(events: readonly RunEvent[]): { cap: number | null; sent: number } {
  const grant = [...events].reverse().find((e) => e.type === "budget.granted");
  const cap = (grant?.data as { cap?: unknown } | undefined)?.cap;
  const sent = events.filter((e) => {
    const data = e.data as { direction?: unknown; outbox_id?: unknown } | undefined;
    return (
      (e.type === "data.transfer" && data?.direction === "out") ||
      (e.type === "artifact.delivered" &&
        typeof data?.outbox_id === "string" &&
        !events.some(
          (transfer) =>
            transfer.type === "data.transfer" &&
            (transfer.data as { outbox_id?: unknown } | undefined)?.outbox_id === data.outbox_id,
        ))
    );
  }).length;
  return { cap: typeof cap === "number" && Number.isFinite(cap) && cap > 0 ? cap : null, sent };
}

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
