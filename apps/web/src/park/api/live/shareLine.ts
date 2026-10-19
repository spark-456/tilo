// BQ-CTX-TEAMWORLD (ADR-0040 decision 9, FR-TEAM-02; HR-1): the world's sharing line, derived only from the world's
// recorded `world.share_changed` events (data `team`, `state` on or off), the latest per team by `seq`. Nothing is
// inferred: no event is no line, and a feed this reader cannot be sure of is no line either (null), never a guess.
// The route is the one Story and Trace read, `GET /worlds/{id}/events`; a team reader's feed does not carry the
// event today (it is owner-only, `vis: []`, ADR-0009), so for them the line is simply absent.
import type { HttpClient } from "../../../api/http";

export interface ShareLine {
  /** Teams whose latest recorded event says on. */
  readonly on: readonly string[];
  /** Teams whose latest recorded event says off. */
  readonly off: readonly string[];
}

export type FeedClient = Pick<HttpClient, "getJson">;

const rec = (v: unknown): Record<string, unknown> | null =>
  typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

/** The line from a list of events, or null when a share event in it cannot be read with certainty. */
export function shareLineFromEvents(events: readonly unknown[], worldId: string): ShareLine | null {
  const latest = new Map<string, { seq: number; on: boolean }>();
  for (const raw of events) {
    const e = rec(raw);
    if (e?.type !== "world.share_changed") continue;
    const data = rec(e.data);
    const team = data?.team;
    const state = data?.state;
    if (
      typeof e.seq !== "number" ||
      !Number.isFinite(e.seq) ||
      (e.world_id !== undefined && e.world_id !== worldId) ||
      typeof team !== "string" ||
      team === "" ||
      (state !== "on" && state !== "off")
    )
      return null;
    const seen = latest.get(team);
    if (!seen || e.seq > seen.seq) latest.set(team, { seq: e.seq, on: state === "on" });
  }
  const teams = [...latest.entries()].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return {
    on: teams.filter(([, v]) => v.on).map(([t]) => t),
    off: teams.filter(([, v]) => !v.on).map(([t]) => t),
  };
}

/** Reads the world's events once; null for any failure or any feed that is not a list of events. */
export async function readShareLine(
  client: FeedClient,
  worldId: string,
): Promise<ShareLine | null> {
  try {
    const body = rec(await client.getJson(`/worlds/${encodeURIComponent(worldId)}/events`));
    return body && Array.isArray(body.events) ? shareLineFromEvents(body.events, worldId) : null;
  } catch {
    return null;
  }
}
