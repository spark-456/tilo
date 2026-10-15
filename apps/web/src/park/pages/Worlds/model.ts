// Pure rules of the Worlds page (STUDIO-3, design/studio-v2 "Tilo S Worlds.dc.html"): which worlds a filter keeps,
// in which order, what the status pill says and the town counts. No React, no clock.
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
  ["running", "Working"],
  ["needs", "Needs you"],
  ["scheduled", "Scheduled"],
  ["finished", "Done"],
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
  running: "Working",
  scheduled: "Scheduled",
  finished: "Done",
};

/** The search and scale filters, which the status tab counts also follow. */
const inBase = (w: World, q: string, tier: TierFilter): boolean =>
  (!q.trim() || w.name.toLowerCase().includes(q.trim().toLowerCase())) &&
  (tier === "all" || w.tier === tier);
/** "Working" also holds a world that needs you. */
const inStatus = (w: World, f: StatusFilter): boolean =>
  f === "all" || w.st === f || (f === "running" && w.st === "needs");

export const countFor = (
  all: readonly World[],
  q: string,
  tier: TierFilter,
  f: StatusFilter,
): number => all.filter((w) => inBase(w, q, tier) && inStatus(w, f)).length;

/** The worlds to draw: filtered, then needs first, working, scheduled, done, each in source order. */
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
    // No served count (none loaded, or a failed read) says no number rather than "0 decisions" (BQ-UX11-1)
    label:
      w.st === "needs"
        ? needsLeft > 0
          ? plural(needsLeft, "decision", "decisions")
          : "Needs you"
        : WORD[w.st],
    tone: TONE[w.st],
  };
}

/** The "Your town" counts: every world by state, and the helpers (agents) of the worlds still at work. */
export interface TownCounts {
  worlds: number;
  helpers: number;
  working: number;
  needs: number;
  scheduled: number;
  done: number;
}

export function townCounts(all: readonly World[]): TownCounts {
  const n = (st: WorldState) => all.filter((w) => w.st === st).length;
  return {
    worlds: all.length,
    helpers: all
      .filter((w) => w.st === "running" || w.st === "needs")
      .reduce((sum, w) => sum + (Number.isFinite(w.agents) ? w.agents : 0), 0),
    working: n("running"),
    needs: n("needs"),
    scheduled: n("scheduled"),
    done: n("finished"),
  };
}

/** The line under a card's name: the list's own "when", else its subtitle and what comes next; never invented. */
export const lastLine = (w: World): string =>
  w.when || [w.meta, [w.nextL, w.nextV].filter(Boolean).join(" ")].filter(Boolean).join(" · ");
