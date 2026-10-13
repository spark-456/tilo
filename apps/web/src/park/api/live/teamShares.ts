// BQ-CTX-TEAMWORLD (ADR-0040, FR-TEAM-01/02): the web's reading of the team-sharing routes of services/api,
// `GET|PUT|DELETE /worlds/{id}/team-shares[/{team}]` (owner only). Every reply is read strictly: a body that is not the
// documented shape is an unreadable reply and is never shown as a result. Nothing here is a sample.
import { type HttpClient, TiloApiError } from "../../../api/http";

export const REASON_WORDS = {
  revoked: "Sharing was turned off.",
  owner_left_team: "You left this team, so this share stopped.",
  owner_changed: "This world changed owner, so this share stopped.",
  not_yet: "This share has not started yet.",
} as const;
export type ShareReason = keyof typeof REASON_WORDS;

export interface TeamShare {
  readonly team: string;
  readonly inForce: boolean;
  readonly reason: ShareReason | null;
  readonly grantedAt: string;
}
export type ShareClient = Pick<HttpClient, "getJson" | "sendJson">;

const BAD_REPLY = "Tilo sent a reply this page could not read.";
const unreadable = (write = false) => new TiloApiError(BAD_REPLY, 200, true, write);
const path = (worldId: string) => `/worlds/${encodeURIComponent(worldId)}`;
const rec = (v: unknown): Record<string, unknown> | null =>
  typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0;

export function sharesFromBody(body: unknown, worldId: string): TeamShare[] | null {
  const b = rec(body);
  if (!b || b.world_id !== worldId || !Array.isArray(b.shares)) return null;
  const rows: TeamShare[] = [];
  for (const raw of b.shares) {
    const r = rec(raw);
    const reason = r?.reason;
    if (!r || !text(r.team) || typeof r.in_force !== "boolean" || !text(r.granted_at)) return null;
    if (reason !== null && !(typeof reason === "string" && reason in REASON_WORDS)) return null;
    if (r.in_force !== (reason === null)) return null; // in force has no reason, a lapse has one
    rows.push({
      team: r.team,
      inForce: r.in_force,
      reason: reason as ShareReason | null,
      grantedAt: r.granted_at,
    });
  }
  return rows;
}

/** The owner's list of the world's shares, revoked ones left out (they are "not shared"). */
export async function readShares(client: ShareClient, worldId: string): Promise<TeamShare[]> {
  const rows = sharesFromBody(await client.getJson(`${path(worldId)}/team-shares`), worldId);
  if (!rows) throw unreadable();
  return rows.filter((s) => s.reason !== "revoked");
}

/** Turns sharing with `team` on or off. Resolves only when the server's own answer names this change. */
export async function setShare(
  client: ShareClient,
  worldId: string,
  team: string,
  on: boolean,
): Promise<void> {
  const body = rec(
    await client.sendJson(
      on ? "PUT" : "DELETE",
      `${path(worldId)}/team-shares/${encodeURIComponent(team)}`,
    ),
  );
  if (body?.world_id !== worldId || body.team !== team || body.state !== (on ? "on" : "off"))
    throw unreadable(true);
}

/** What a person reads for a failed call: the client's own sentence, or a plain one for a reply it could not read. */
export const failureWords = (error: unknown): string =>
  error instanceof TiloApiError ? error.message : BAD_REPLY;
export const isMissing = (error: unknown): boolean =>
  error instanceof TiloApiError && error.status === 404;
