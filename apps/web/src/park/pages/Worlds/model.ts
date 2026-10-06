// Pure rules of the Worlds page (design "Tilo App Worlds.dc.html", renderVals()): which worlds a filter keeps,
// in which order, and what the status chip says. No React, no clock.
import type { TierName, World, WorldState } from "../../api/types";

export type StatusFilter = "all" | WorldState;
export type TierFilter = "all" | TierName;
export type Tone = "needs" | "run" | "sch" | "ok";
export interface Status {
  label: string;
  tone: Tone;
}

export const STATUS_TABS: ReadonlyArray<readonly [StatusFilter, string]> = [
  ["all", "All"],
  ["needs", "Needs you"],
  ["running", "Running"],
  ["scheduled", "Scheduled"],
  ["finished", "Ready"],
];
export const SCALES: ReadonlyArray<readonly [TierFilter, string]> = [
  ["all", "All sizes"],
  ["City", "Cities"],
  ["Town", "Towns"],
  ["Village", "Villages"],
];

const ORDER: Record<WorldState, number> = { needs: 0, running: 1, scheduled: 2, finished: 3 };
const TONE: Record<WorldState, Tone> = {
  needs: "needs",
  running: "run",
  scheduled: "sch",
  finished: "ok",
};
const WORD: Record<WorldState, string> = {
  needs: "",
  running: "Running",
  scheduled: "Scheduled",
  finished: "Ready",
};

/** The search and scale filters, which the status tab counts also follow. */
const inBase = (w: World, q: string, tier: TierFilter): boolean =>
  (!q || w.name.toLowerCase().includes(q.toLowerCase())) && (tier === "all" || w.tier === tier);
/** "Running" also holds a world that needs you. */
const inStatus = (w: World, f: StatusFilter): boolean =>
  f === "all" || w.st === f || (f === "running" && w.st === "needs");

export const countFor = (
  all: readonly World[],
  q: string,
  tier: TierFilter,
  f: StatusFilter,
): number => all.filter((w) => inBase(w, q, tier) && inStatus(w, f)).length;

/** The worlds to draw: filtered, then needs first, running, scheduled, ready, each in source order. */
export const visibleWorlds = (
  all: readonly World[],
  q: string,
  tier: TierFilter,
  f: StatusFilter,
): World[] =>
  all.filter((w) => inBase(w, q, tier) && inStatus(w, f)).sort((a, b) => ORDER[a.st] - ORDER[b.st]);

export const plural = (n: number, one: string, many: string): string =>
  `${n} ${n === 1 ? one : many}`;

export function statusOf(w: World, needsLeft: number): Status {
  if (w.isNew) return { label: "Starting", tone: TONE[w.st] };
  return {
    label: w.st === "needs" ? plural(needsLeft, "decision", "decisions") : WORD[w.st],
    tone: TONE[w.st],
  };
}
