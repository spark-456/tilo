// FR-UX-11: read-only bell data. No sample subtitles, inferred outcomes or local time guesses.
import { TiloApiError } from "../../../api/http";
import type { Notification } from "../types";
import { decisionKey } from "./decisionsFromCards";

const text = (v: unknown): v is string => typeof v === "string" && v.length > 0;
export function notificationsFromFeed(body: unknown): Notification[] {
  const feed = body as { notifications?: unknown; count?: unknown } | null;
  if (
    !Array.isArray(feed?.notifications) ||
    !Number.isInteger(feed.count) ||
    (feed.count as number) < feed.notifications.length
  ) {
    throw new TiloApiError("Tilo sent a notification reply this page could not read.", 200, true);
  }
  return feed.notifications.map((row: unknown) => {
    const n = row as Record<string, unknown> | null;
    if (
      !n ||
      !text(n.id) ||
      !text(n.world_id) ||
      !text(n.title) ||
      !text(n.created_at) ||
      !Number.isFinite(Date.parse(n.created_at)) ||
      (n.kind !== "needs" && n.kind !== "done") ||
      (n.card_id !== null && !text(n.card_id))
    ) {
      throw new TiloApiError("Tilo sent a notification reply this page could not read.", 200, true);
    }
    return {
      id: n.id,
      title: n.title,
      kind: n.kind,
      t: n.created_at,
      sub: "",
      go: ["world", n.world_id],
      ...(n.kind === "needs" && text(n.card_id) ? { dec: decisionKey(n.world_id, n.card_id) } : {}),
    };
  });
}
