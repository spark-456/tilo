// TEAM-WEB (FR-TEAM-02/04, FR-ACC-01): the shapes tilo-api's team routes answer (services/api team_routes.py),
// written by hand because no contracts-ts type exists for them, the guard that decides a body is one, and the
// plain sentences each outcome gets. Nothing here reads the fixtures (HR-1..HR-7).
import { TiloApiError } from "../../../api/http";

export const TEAM_ROLES = ["Owner", "Approver", "Member", "Viewer"] as const;
export const TOOL_LEVELS = ["off", "read", "draft", "act"] as const;
export type ToolLevelName = (typeof TOOL_LEVELS)[number];

export interface TeamMemberRow {
  id: string;
  role: string;
  /** INR minor units; null when none is set or the viewer may not see it (only the Owner and the person see it). */
  limit_minor: number | null;
}
export interface TeamSwitchRow {
  key: string;
  on: boolean;
  must_ask: boolean;
}
export interface TeamToolRow {
  connector: string;
  level: string;
}
export interface TeamCapability {
  key: string;
  label: string;
  roles: string[];
}
export interface TeamInviteRow {
  id: string;
  email: string;
  role: string;
}
/** `GET /v1/team` and what every write answers (except an invite, which answers its id and is followed by a read). */
export interface TeamView {
  version: number;
  me: { id: string; role: string };
  members: TeamMemberRow[];
  switches: TeamSwitchRow[];
  tools: TeamToolRow[];
  capabilities: TeamCapability[];
  invites: TeamInviteRow[];
}

/** One Owner-only write. The server applies it with a compare-and-set; the page sends no version. */
export type TeamOp =
  | { kind: "role"; id: string; role: string }
  | { kind: "limit"; id: string; limitMinor: number | null }
  | { kind: "remove"; id: string }
  | { kind: "invite"; email: string; role: string }
  | { kind: "switch"; key: string; on: boolean }
  | { kind: "tool"; connector: string; level: string };

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;
const isStr = (v: unknown): v is string => typeof v === "string";
const each = (v: unknown, ok: (x: Record<string, unknown>) => boolean): boolean =>
  Array.isArray(v) && v.every((x) => isObj(x) && ok(x));

/** A body that is not a team view is an unreadable reply, never a team. */
export function isTeamView(v: unknown): v is TeamView {
  if (!isObj(v) || typeof v.version !== "number" || !isObj(v.me)) return false;
  return (
    isStr(v.me.id) &&
    isStr(v.me.role) &&
    each(
      v.members,
      (m) =>
        isStr(m.id) &&
        isStr(m.role) &&
        (m.limit_minor === null || typeof m.limit_minor === "number"),
    ) &&
    each(
      v.switches,
      (s) => isStr(s.key) && typeof s.on === "boolean" && typeof s.must_ask === "boolean",
    ) &&
    each(v.tools, (t) => isStr(t.connector) && isStr(t.level)) &&
    each(
      v.capabilities,
      (c) => isStr(c.key) && isStr(c.label) && Array.isArray(c.roles) && c.roles.every(isStr),
    ) &&
    each(v.invites, (i) => isStr(i.id) && isStr(i.email) && isStr(i.role))
  );
}

/** Where the request goes: method, path (under the API origin) and JSON body. */
export function requestOf(op: TeamOp): { method: string; path: string; body?: unknown } {
  const e = encodeURIComponent;
  switch (op.kind) {
    case "role":
      return { method: "PUT", path: `/v1/team/members/${e(op.id)}/role`, body: { role: op.role } };
    case "limit":
      return {
        method: "PUT",
        path: `/v1/team/members/${e(op.id)}/limit`,
        body: { limit_minor: op.limitMinor },
      };
    case "remove":
      return { method: "DELETE", path: `/v1/team/members/${e(op.id)}` };
    case "invite":
      return { method: "POST", path: "/v1/team/invites", body: { email: op.email, role: op.role } };
    case "switch":
      return { method: "PUT", path: `/v1/team/switches/${e(op.key)}`, body: { on: op.on } };
    case "tool":
      return {
        method: "PUT",
        path: `/v1/team/tools/${e(op.connector)}`,
        body: { level: op.level },
      };
  }
}

export const NOT_SET_UP = "Team controls are not set up on this install yet.";

/** What a person reads for a failed team call. 422 keeps the server's own plain sentence (it says what to pick);
 * every other outcome gets ours, so a code like `not_configured` never shows. */
export function teamErrorText(e: unknown): string {
  if (!(e instanceof TiloApiError)) return "Tilo could not do that. Try again.";
  if (e.replayOnly) return e.message;
  switch (e.status) {
    case 401:
      return "Sign in again to manage the team.";
    case 403:
      return "Only an Owner signed in on the web can change this.";
    case 404:
      return "That person or setting is no longer on the team.";
    case 409:
      return "Someone else changed the team. Showing the latest.";
    case 422:
      return e.message;
    case 503:
      return NOT_SET_UP;
    default:
      return e.message;
  }
}

/** What a person reads when the team cannot be read at all (a GET): a 403 and a 404 say who may look. */
export function readErrorText(e: unknown): string {
  if (e instanceof TiloApiError && !e.replayOnly) {
    if (e.status === 403)
      return "Team settings need a full sign-in on the web. Sign in there to see them.";
    if (e.status === 404) return "You are not on this team.";
  }
  return teamErrorText(e);
}

/** The failures that mean "show the current state again" (a stale write). */
export const isStale = (e: unknown): boolean => e instanceof TiloApiError && e.status === 409;

/** The view as it will look once `op` is accepted: the optimistic copy (rolled back if the call fails). */
export function applyOp(v: TeamView, op: TeamOp): TeamView {
  switch (op.kind) {
    case "role":
      return {
        ...v,
        members: v.members.map((m) => (m.id === op.id ? { ...m, role: op.role } : m)),
      };
    case "limit":
      return {
        ...v,
        members: v.members.map((m) => (m.id === op.id ? { ...m, limit_minor: op.limitMinor } : m)),
      };
    case "remove":
      return { ...v, members: v.members.filter((m) => m.id !== op.id) };
    case "switch":
      return {
        ...v,
        switches: v.switches.map((s) => (s.key === op.key ? { ...s, on: op.on } : s)),
      };
    case "tool":
      return {
        ...v,
        tools: v.tools.map((t) => (t.connector === op.connector ? { ...t, level: op.level } : t)),
      };
    case "invite":
      return v;
  }
}
