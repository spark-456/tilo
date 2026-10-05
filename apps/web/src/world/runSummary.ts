// What the world screens say about a run, derived from its recorded events alone (HR-1, HR-5):
// the status of the run, the approved budget and the words for states and ranks. No layout needed.
import type { Event, Layout } from "@tilo/contracts";
import { isKnownType } from "./registry";

export type RunStatus = "idle" | "started" | "paused" | "completed" | "failed";

/** The run's status from its latest registered world.* event; "idle" until one says otherwise. */
export function worldStatus(events: readonly Event[]): RunStatus {
  let status: RunStatus = "idle";
  for (const e of events) {
    if (!isKnownType(e.type)) continue; // HR-5: an unregistered type changes nothing
    if (e.type === "world.started" || e.type === "world.resumed") status = "started";
    else if (e.type === "world.paused") status = "paused";
    else if (e.type === "world.completed") status = "completed";
    else if (e.type === "world.failed") status = "failed";
  }
  return status;
}

/** True once the run has ended, either way. */
export const runEnded = (status: RunStatus): boolean =>
  status === "completed" || status === "failed";

/** The budget the person approved: the cap on the latest budget.granted event, or null. */
export function budgetCap(events: readonly Event[]): number | null {
  let cap: number | null = null;
  for (const e of events) {
    if (e.type !== "budget.granted") continue;
    const value = (e.data as { cap?: unknown }).cap;
    if (typeof value === "number") cap = value;
  }
  return cap;
}

export const RUN_STATUS_LABEL: Readonly<Record<RunStatus, string>> = {
  idle: "Getting ready",
  started: "Working",
  paused: "Paused",
  completed: "Done",
  failed: "Stopped with an error",
};

export const BUILDING_STATE = {
  hidden: "Not planned yet",
  planned: "Planned",
  constructing: "Being built",
  operational: "At work",
  completed: "Finished",
  archived: "Archived",
} as const;

/** The words for a channel island's state, shared by the stage tags and the Inspect panel. */
export const ISLAND_STATE = {
  locked: "Locked",
  requested: "Waiting for consent",
  connected: "Connected",
  failed: "Connection lost",
} as const;

/** "specialist" becomes "Specialist"; underscores become spaces. */
export const rankName = (rank: string): string => {
  const words = rank.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** "Specialist 1", "Specialist 2" when a rank repeats; "Director" when it does not. */
export function agentNames(layout: Layout): Map<string, string> {
  const count = new Map<string, number>();
  for (const a of layout.semantic.agents) count.set(a.rank, (count.get(a.rank) ?? 0) + 1);
  const seen = new Map<string, number>();
  const names = new Map<string, string>();
  for (const a of layout.semantic.agents) {
    const n = (seen.get(a.rank) ?? 0) + 1;
    seen.set(a.rank, n);
    names.set(a.id, (count.get(a.rank) ?? 0) > 1 ? `${rankName(a.rank)} ${n}` : rankName(a.rank));
  }
  return names;
}
