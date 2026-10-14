// BQ-CTX-TEAMWORLD (ADR-0040, FR-TEAM-01..06): the web's reading of the team-sharing routes of services/api.
// `GET|PUT|DELETE /worlds/{id}/team-shares[/{team}]` (owner only), `GET /worlds/{id}` (owner or team reader) and
// `GET /worlds/{id}/work-items` (the team view of items made in the world). Every reply is read strictly: a body that
// is not the documented shape is an unreadable reply and is never shown as a result. Nothing here is a sample.
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
export interface TeamItem {
  readonly id: string;
  readonly title: string;
  readonly status: "open" | "done";
  readonly due: string | null;
  /** The owner's user id; the page turns it into a name only when the directory gives one. */
  readonly owner: string;
}
export interface SharedWorld {
  readonly districts: readonly { id: string; name: string; summary: string }[];
  readonly hasHiddenDistricts: boolean;
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

export interface TeamItems {
  readonly items: TeamItem[];
  /** The server cut the list at its cap: not every row is shown. */
  readonly truncated: boolean;
}

export function itemsFromBody(body: unknown, worldId: string): TeamItems | null {
  const b = rec(body);
  if (!b || b.world_id !== worldId || !Array.isArray(b.items)) return null;
  const rows: TeamItem[] = [];
  for (const raw of b.items) {
    const r = rec(raw);
    if (!r || !text(r.id) || !text(r.title) || !text(r.owner) || r.world_id !== worldId)
      return null;
    if (r.status !== "open" && r.status !== "done") return null;
    if (r.due !== null && !text(r.due)) return null;
    rows.push({ id: r.id, title: r.title, status: r.status, due: r.due, owner: r.owner });
  }
  return { items: rows, truncated: b.truncated === true };
}

export function sharedWorldFromBody(body: unknown, worldId: string): SharedWorld | null {
  const b = rec(body);
  if (!b || b.world_id !== worldId || !Array.isArray(b.districts)) return null;
  const districts: { id: string; name: string; summary: string }[] = [];
  for (const raw of b.districts) {
    const d = rec(raw);
    if (!d || !text(d.id) || !text(d.name) || typeof d.summary !== "string") return null;
    districts.push({ id: d.id, name: d.name, summary: d.summary });
  }
  return { districts, hasHiddenDistricts: b.has_hidden_districts === true };
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

export async function readTeamItems(client: ShareClient, worldId: string): Promise<TeamItems> {
  const got = itemsFromBody(await client.getJson(`${path(worldId)}/work-items`), worldId);
  if (!got) throw unreadable();
  return got;
}

export async function readSharedWorld(client: ShareClient, worldId: string): Promise<SharedWorld> {
  const world = sharedWorldFromBody(await client.getJson(path(worldId)), worldId);
  if (!world) throw unreadable();
  return world;
}

/** What a person reads for a failed call: the client's own sentence, or a plain one for a reply it could not read. */
export const failureWords = (error: unknown): string =>
  error instanceof TiloApiError ? error.message : BAD_REPLY;
export const isMissing = (error: unknown): boolean =>
  error instanceof TiloApiError && error.status === 404;
