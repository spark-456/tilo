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

/** The size chips (the layout's tier, the artboard's "All sizes / Village / Town / City"). */
export const SIZES = ["all", "outpost", "village", "town", "city"] as const;
export type Size = (typeof SIZES)[number];

export const SIZE_LABEL: Readonly<Record<Size, string>> = {
  all: "All sizes",
  outpost: "Outpost",
  village: "Village",
  town: "Town",
  city: "City",
};

/** What the run says about a world: `recorded` until its first event, then `running` until it
 * ends. A failed run is neither running nor finished: only All lists it. */
export type WorldPhase = "recorded" | "running" | "finished" | "failed";

export interface WorldRow {
  readonly title: string;
  readonly phase: WorldPhase;
  /** Cards waiting for a person in this world. */
  readonly waiting: number;
  /** The layout's tier; null until the layout has loaded (only All sizes lists such a world). */
  readonly size: string | null;
}

export const inSize = (w: WorldRow, s: Size): boolean => s === "all" || w.size === s;

export const inFilter = (w: WorldRow, f: Filter): boolean =>
  f === "all" ||
  (f === "needs" && w.waiting > 0) ||
  (f === "running" && w.phase === "running") ||
  (f === "finished" && w.phase === "finished");

export const matchesQuery = (w: WorldRow, query: string): boolean => {
  const q = query.trim().toLowerCase();
  return q === "" || w.title.toLowerCase().includes(q);
};

/** The count on each chip, over the worlds the search and the size let through. */
export function countsOf(
  worlds: readonly WorldRow[],
  query: string,
  size: Size = "all",
): Record<Filter, number> {
  const found = worlds.filter((w) => matchesQuery(w, query) && inSize(w, size));
  return Object.fromEntries(
    FILTERS.map((f) => [f, found.filter((w) => inFilter(w, f)).length]),
  ) as Record<Filter, number>;
}

export const visible = (
  worlds: readonly WorldRow[],
  f: Filter,
  query: string,
  size: Size = "all",
): WorldRow[] => worlds.filter((w) => matchesQuery(w, query) && inFilter(w, f) && inSize(w, size));
