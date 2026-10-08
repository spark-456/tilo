// NOTIF-1: tilo-api `GET /v1/notifications` rows as Park notifications. Only the served fields carry values:
// the title is the API's fixed text, `sub` is empty (the API serves no subtitle) and there is no "warn" kind
// (BQ-NOTIF-1). A "needs" row with a card links to its decision; every row opens its world. Pure: it never
// mutates its input and never imports fixtures (HR-1..HR-7).
import type { Notification } from "../types";
import { decisionKey } from "./decisionsFromCards";

export interface NotificationRow {
  id: string;
  kind: "needs" | "done";
  created_at: string;
  world_id: string;
  title: string;
  card_id: string | null;
  artifact_id: string | null;
}

const text = (v: unknown): v is string => typeof v === "string" && v !== "";
const orNull = (v: unknown): boolean => v === null || text(v);

export function isNotificationRow(v: unknown): v is NotificationRow {
  const r = v as Record<string, unknown> | null;
  return (
    typeof r === "object" &&
    r !== null &&
    text(r.id) &&
    (r.kind === "needs" || r.kind === "done") &&
    text(r.created_at) &&
    text(r.world_id) &&
    text(r.title) &&
    orNull(r.card_id) &&
    orNull(r.artifact_id)
  );
}

/** A body that is not the bell's page is an unreadable reply, never notifications. */
export function isNotificationPage(v: unknown): v is { notifications: NotificationRow[] } {
  const p = v as { notifications?: unknown } | null;
  return (
    typeof p === "object" &&
    p !== null &&
    Array.isArray(p.notifications) &&
    p.notifications.every(isNotificationRow)
  );
}

/** "HH:MM" (UTC) of an ISO stamp, read from its text: the api layer has no clock. The raw stamp when it is not ISO. */
function clock(stamp: string): string {
  return /^\d{4}-\d\d-\d\dT(\d\d:\d\d)/.exec(stamp)?.[1] ?? stamp;
}

function notificationOf(row: NotificationRow): Notification {
  const n: Notification = {
    id: row.id,
    t: clock(row.created_at),
    title: row.title,
    sub: "",
    kind: row.kind,
    go: ["world", row.world_id],
  };
  if (row.kind === "needs" && row.card_id !== null) n.dec = decisionKey(row.world_id, row.card_id);
  return n;
}

export function notificationsFromApi(rows: readonly NotificationRow[]): Notification[] {
  return rows.map(notificationOf);
}
