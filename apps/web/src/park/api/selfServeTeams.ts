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
  };
}
