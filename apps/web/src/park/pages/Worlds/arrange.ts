// WORLDS-MANAGE (owner, 21 Oct: "add an option to delete worlds from the worlds section since it is getting cluttered
// and no way to arrange it"): how the person orders their worlds, which they pinned to the top, and which they picked
// to delete. Pure rules, no React, no clock. The sort and the pins are this browser's own conveniences (shared/worldsPrefs.ts,
// never sent anywhere); nothing here invents a date or a state the list did not serve.
import type { World } from "../../api/types";
import {
  readPinnedPref,
  readSortPref,
  writePinnedPref,
  writeSortPref,
} from "../../shared/worldsPrefs";

export type SortKey = "status" | "newest" | "oldest" | "name";

export const SORTS: ReadonlyArray<readonly [SortKey, string]> = [
  ["status", "Status"],
  ["newest", "Newest first"],
  ["oldest", "Oldest first"],
  ["name", "Name A–Z"],
];

const STATE_ORDER: Record<World["st"], number> = {
  needs: 0,
  running: 1,
  scheduled: 2,
  finished: 3,
};

/** A served start time as a number, or null when the list gave none (it then sorts last, never guessed). */
const startedAt = (w: World): number | null => {
  const t = Date.parse(w.started);
  return Number.isFinite(t) ? t : null;
};

function byStart(a: World, b: World, newest: boolean): number {
  const x = startedAt(a);
  const y = startedAt(b);
  if (x === null && y === null) return 0;
  if (x === null) return 1;
  if (y === null) return -1;
  return newest ? y - x : x - y;
}

/** The worlds in the chosen order, pinned ones first (each group keeps that order). The sort is stable. */
export function arrange(
  list: readonly World[],
  sort: SortKey,
  pinned: ReadonlySet<string>,
): World[] {
  const order = (a: World, b: World): number => {
    if (sort === "name") return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
    if (sort === "newest" || sort === "oldest") return byStart(a, b, sort === "newest");
    return STATE_ORDER[a.st] - STATE_ORDER[b.st];
  };
  return [...list].sort(
    (a, b) => Number(pinned.has(b.id)) - Number(pinned.has(a.id)) || order(a, b),
  );
}

/** A world the person may delete: their own (not a teammate's shared world), not the recorded sample (that one is
 * hidden with "Hide sample project"). */
export const deletable = (w: World): boolean => w.access !== "team" && !w.sample;

/** A world still at work (its run is going): the server refuses to delete it until it is paused ("Stop and delete"). */
export const stillWorking = (w: World): boolean => w.st === "running";

/** The stored order, else "status". */
export const readSort = (): SortKey =>
  readSortPref(
    SORTS.map(([key]) => key),
    "status",
  );
export const writeSort = (sort: SortKey): void => writeSortPref(sort);
export const readPinned = (): Set<string> => readPinnedPref();
export const writePinned = (pinned: ReadonlySet<string>): void => writePinnedPref(pinned);

/** What the delete dialog says it will do, from the worlds picked (names quoted, the working ones counted). */
export function deleteSummary(picked: readonly World[]): { title: string; working: number } {
  const working = picked.filter(stillWorking).length;
  const first = picked[0];
  const title =
    picked.length === 1 && first ? `Delete “${first.name}”?` : `Delete ${picked.length} worlds?`;
  return { title, working };
}
