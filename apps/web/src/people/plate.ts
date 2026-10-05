// The plate's order and the three actions on it (FR-PA-02, FR-PA-03), as pure functions over work
// items. The order is code, not a model: overdue, then due in the next 48 hours, then the rest;
// within a group by due date, then creation, then id, so the same items always list the same way.
import type { WorkItem } from "@tilo/contracts";
import { PREVIEW_NOW, PREVIEW_TODAY, SIGNED_IN } from "./data";

export type Bucket = "overdue" | "soon" | "rest";
export type Lane = "open" | "snoozed" | "asked" | "done";
export type PlateAction = { kind: "done" | "snooze" | "not_mine" | "put_back"; id: string };

const DAY = 86_400_000;
const addDays = (date: string, n: number): string =>
  new Date(Date.parse(`${date}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);

/** The bucket of a due date: before today is overdue, up to two days on is soon. */
export function bucketOf(due: string | null, today = PREVIEW_TODAY): Bucket {
  if (due === null) return "rest";
  if (due < today) return "overdue";
  return due <= addDays(today, 2) ? "soon" : "rest";
}

/** Where an item sits: done, asked to be reassigned (last history entry), snoozed, or open. */
export function laneOf(item: WorkItem, now = PREVIEW_NOW): Lane {
  if (item.status === "done") return "done";
  if (item.history.at(-1)?.change === "reassign_requested") return "asked";
  return item.snoozed_until !== null && item.snoozed_until > now ? "snoozed" : "open";
}

export const byDue = (a: WorkItem, b: WorkItem): number =>
  (a.due ?? "9999").localeCompare(b.due ?? "9999") ||
  a.created_at.localeCompare(b.created_at) ||
  a.id.localeCompare(b.id);

/** "Not mine" is for an item someone else assigned: a person-made item is its creator's own (PE-03). */
export const canReject = (item: WorkItem): boolean =>
  item.assigned_by !== null && item.assigned_by.by !== item.owner;

export const SNOOZE_UNTIL = new Date(Date.parse(PREVIEW_NOW) + DAY).toISOString();

const CHANGE = {
  done: "done",
  snooze: "snoozed",
  not_mine: "reassign_requested",
  put_back: "reopened",
} as const;

/** Apply one action to one item and record it in the item's history, as the contract defines it.
 * Only the signed-in person's own item changes, and "not mine" only on an item someone else
 * assigned (PE-03): the screen hides the button, and this refuses it too. "Put back" undoes done,
 * snooze or a reassign request. */
export function reducePlate(items: readonly WorkItem[], a: PlateAction): readonly WorkItem[] {
  return items.map((i) => {
    if (i.id !== a.id || i.owner !== SIGNED_IN) return i;
    if (a.kind === "not_mine" && !canReject(i)) return i;
    const status = a.kind === "done" ? "done" : a.kind === "put_back" ? "open" : i.status;
    const entry = { at: PREVIEW_NOW, by: SIGNED_IN, change: CHANGE[a.kind], status } as const;
    return {
      ...i,
      status,
      snoozed_until:
        a.kind === "snooze" ? SNOOZE_UNTIL : a.kind === "put_back" ? null : i.snoozed_until,
      history: [...i.history, entry],
      updated_at: PREVIEW_NOW,
    };
  });
}
