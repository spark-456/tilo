import type { Notification } from "../types";
import { decisionKey } from "./decisionsFromCards";

/** FR-UX-11, HR-1: titles and times as served, no fabricated world description or relative time. */
export function notificationsFromList(body: unknown): Notification[] | null {
  if (
    !body ||
    typeof body !== "object" ||
    !("notifications" in body) ||
    !Array.isArray(body.notifications) ||
    !("count" in body) ||
    typeof body.count !== "number" ||
    !Number.isInteger(body.count) ||
    body.count < body.notifications.length
  )
    return null;
  const rows: Notification[] = [];
  for (const n of body.notifications) {
    if (
      !n ||
      typeof n !== "object" ||
      typeof n.id !== "string" ||
      !n.id ||
      typeof n.world_id !== "string" ||
      !n.world_id ||
      typeof n.title !== "string" ||
      typeof n.created_at !== "string" ||
      !["needs", "done"].includes(n.kind) ||
      !(n.card_id === null || typeof n.card_id === "string") ||
      !(n.artifact_id === null || typeof n.artifact_id === "string")
    )
      return null;
    rows.push({
      id: n.id,
      title: n.title,
      kind: n.kind,
      t: n.created_at,
      sub: "",
      go: ["world", n.world_id],
      ...(n.kind === "needs" && n.card_id ? { dec: decisionKey(n.world_id, n.card_id) } : {}),
    });
  }
  return rows;
}
