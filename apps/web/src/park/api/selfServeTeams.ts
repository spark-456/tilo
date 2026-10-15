// SELF-SERVE-TEAMS (ADR-0044, PE-37): the signed-in person's own teams. Any member creates a team and leads it,
// a lead invites by email (the server answers the same whatever the address), the invited person accepts or
// declines. Every decision is the server's; this module only reads and sends, and shows only what the server said.
// The live api installs one client (liveApi.ts); without one (sample or fixture mode) the panel renders nothing.

export interface TeamsTransport {
  getJson(path: string): Promise<unknown>;
  postJson(path: string, body: unknown): Promise<unknown>;
}

export interface MyTeam {
  team: string;
  lead: boolean;
  state: "member" | "pending" | "lapsed"; // lapsed: an entry that counts for nothing, removable by its person
  invitedBy: string | null; // the inviter's display name, only while an invitation is pending (PE-20)
}

export interface RosterMember {
  id: string;
  name: string;
  lead: boolean;
}

export interface InviteLinkRow {
  id: string;
  created_at: string;
  expires_at: string;
  state: "unused" | "expired" | "used" | "withdrawn";
}

export interface MadeLink {
  invite_id: string;
  token: string;
  expires_at: string;
}

let transport: TeamsTransport | null = null;

export function installTeamsTransport(next: TeamsTransport | null): void {
  transport = next;
}

const TEAM = /^tm_[0-9a-z_]{1,48}$/;
const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null;

function teamRow(raw: unknown): MyTeam | null {
  if (!isObject(raw) || typeof raw.team !== "string" || !TEAM.test(raw.team)) return null;
  if (raw.state !== "member" && raw.state !== "pending" && raw.state !== "lapsed") return null;
  const by = isObject(raw.invited_by) ? raw.invited_by.display_name : null;
  return {
    team: raw.team,
    lead: raw.lead === true,
    state: raw.state,
    invitedBy: typeof by === "string" ? by : null,
  };
}

const path = (team: string) => `/v1/teams/${encodeURIComponent(team)}`;

export interface TeamsClient {
  mine(): Promise<{ teams: MyTeam[]; you: string | null }>;
  roster(team: string): Promise<RosterMember[]>;
  create(): Promise<void>;
  invite(team: string, email: string): Promise<void>;
  accept(team: string): Promise<void>;
  leave(team: string, me: string): Promise<void>;
  makeLink(team: string): Promise<MadeLink>;
  listLinks(team: string): Promise<InviteLinkRow[]>;
  revokeLink(team: string, id: string): Promise<void>;
  acceptLink(token: string): Promise<{ team: string; state: "member" }>;
  ensurePerson(): Promise<void>;
}

/** The installed client, or null (no live api: nothing is shown and nothing is sent). */
export function teamsClient(): TeamsClient | null {
  const t = transport;
  if (!t) return null;
  return {
    mine: async () => {
      const body = await t.getJson("/v1/teams");
      if (!isObject(body) || !Array.isArray(body.teams)) throw new Error("Teams are unavailable");
      const teams = body.teams.map(teamRow).filter((r): r is MyTeam => r !== null);
      return { teams, you: typeof body.you === "string" ? body.you : null };
    },
    roster: async (team) => {
      const body = await t.getJson(path(team));
      if (!isObject(body) || !Array.isArray(body.members)) throw new Error("Roster is unavailable");
      return body.members.flatMap((m) =>
        isObject(m) && typeof m.id === "string" && typeof m.display_name === "string"
          ? [{ id: m.id, name: m.display_name, lead: m.lead === true }]
          : [],
      );
    },
    create: async () => {
      await t.postJson("/v1/teams", {});
    },
    invite: async (team, email) => {
      await t.postJson(`${path(team)}/invites`, { email });
    },
    accept: async (team) => {
      await t.postJson(`${path(team)}/accept`, {});
    },
    leave: async (team, me) => {
      await t.postJson(`${path(team)}/members/${encodeURIComponent(me)}/remove`, {});
    },
    makeLink: async (team) => {
      const body = await t.postJson(`${path(team)}/invite-links`, {});
      if (
        !isObject(body) ||
        typeof body.invite_id !== "string" ||
        typeof body.token !== "string" ||
        typeof body.expires_at !== "string"
      )
        throw new Error("Invite links are unavailable");
      return { invite_id: body.invite_id, token: body.token, expires_at: body.expires_at };
    },
    listLinks: async (team) => {
      const body = await t.getJson(`${path(team)}/invite-links`);
      const rows = Array.isArray(body) ? body : isObject(body) ? body.links : null;
      if (!Array.isArray(rows)) throw new Error("Invite links are unavailable");
      return rows.flatMap((row): InviteLinkRow[] =>
        isObject(row) &&
        typeof row.id === "string" &&
        typeof row.created_at === "string" &&
        typeof row.expires_at === "string" &&
        ["unused", "expired", "used", "withdrawn"].includes(String(row.state))
          ? [
              {
                id: row.id,
                created_at: row.created_at,
                expires_at: row.expires_at,
                state: row.state as InviteLinkRow["state"],
              },
            ]
          : [],
      );
    },
    revokeLink: async (team, id) => {
      await t.postJson(`${path(team)}/invite-links/${encodeURIComponent(id)}/revoke`, {});
    },
    acceptLink: async (token) => {
      const body = await t.postJson("/v1/team-invite-links/accept", { token });
      if (!isObject(body) || typeof body.team !== "string" || body.state !== "member")
        throw new Error("Invite links are unavailable");
      return { team: body.team, state: "member" };
    },
    ensurePerson: async () => {
      const { session } = await import("../../auth/session");
      const profile = session.getState();
      if (profile.status !== "google" || !profile.email?.trim())
        throw new Error("Sign in with Google first");
      const email = profile.email.trim();
      await t.postJson("/v1/people/first", {
        display_name: profile.displayName?.trim() || email.split("@")[0],
        email,
        aliases: [],
        time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        preferred_channel: "web",
      });
    },
  };
}
