// S-14 filters (PRD 18.3): which worlds a status filter and a search show, and the counts on the
// filter chips. Everything is computed from the worlds the client knows and their recorded events
// (HR-1): nothing is scheduled in this build, so that count is a true zero, not a placeholder.

export const FILTERS = ["all", "needs", "running", "scheduled", "finished"] as const;
export type Filter = (typeof FILTERS)[number];

export const FILTER_LABEL: Readonly<Record<Filter, string>> = {
  all: "All",
  needs: "Needs you",
  running: "Running",
  scheduled: "Scheduled",
  finished: "Finished",
};

/** What the run says about a world: `recorded` until its first event, then `running` until it
 * ends. A failed run is neither running nor finished: only All lists it. */
export type WorldPhase = "recorded" | "running" | "finished" | "failed";

export interface WorldRow {
  readonly title: string;
  readonly phase: WorldPhase;
  /** Cards waiting for a person in this world. */
  readonly waiting: number;
}

export const inFilter = (w: WorldRow, f: Filter): boolean =>
  f === "all" ||
  (f === "needs" && w.waiting > 0) ||
  (f === "running" && w.phase === "running") ||
  (f === "finished" && w.phase === "finished");

export const matchesQuery = (w: WorldRow, query: string): boolean => {
  const q = query.trim().toLowerCase();
  return q === "" || w.title.toLowerCase().includes(q);
};

/** The count on each chip, over the worlds the search lets through. */
export function countsOf(worlds: readonly WorldRow[], query: string): Record<Filter, number> {
  const found = worlds.filter((w) => matchesQuery(w, query));
  return Object.fromEntries(
    FILTERS.map((f) => [f, found.filter((w) => inFilter(w, f)).length]),
  ) as Record<Filter, number>;
}

export const visible = (worlds: readonly WorldRow[], f: Filter, query: string): WorldRow[] =>
  worlds.filter((w) => matchesQuery(w, query) && inFilter(w, f));
