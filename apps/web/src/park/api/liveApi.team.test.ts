// TEAM-WEB (FR-TEAM-02, FR-TEAM-04, FR-ACC-01): the live Api reads GET /v1/team and sends the Owner-only writes
// (services/api team_routes.py). Fixtures keep the default; nothing is fetched without a base url.
import { describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { createFixtureApi } from "./fixtureApi";
import { NotBuilt, createLiveApi } from "./liveApi";
import { applyOp, teamErrorText } from "./live/teamLive";

const BASE = "https://api.example.test";
const VIEW = {
  version: 3,
  me: { id: "u1", role: "Owner" },
  members: [
    { id: "u1", role: "Owner", limit_minor: null },
    { id: "u2", role: "Member", limit_minor: 5000 },
  ],
  switches: [
    { key: "spend", on: true, must_ask: true },
    { key: "weekend", on: false, must_ask: false },
  ],
  tools: [{ connector: "gmail", level: "act" }],
  capabilities: [{ key: "invite_people", label: "Invite people", roles: ["Owner"] }],
  invites: [{ id: "inv_1", email: "a@b.co", role: "Member" }],
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const apiWith = (reply: () => Response) => {
  const fetchSpy = vi.fn(async (_u: string | URL | Request, _i?: RequestInit) => reply());
  return { fetchSpy, api: createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch }) };
};

describe("TEAM_WEB_live_api: GET /v1/team", () => {
  it("TEAM_WEB_getTeamLive_reads_v1_team_as_live", async () => {
    const { fetchSpy, api } = apiWith(() => json(VIEW));
    const r = await api.getTeamLive();
    expect(String(fetchSpy.mock.calls[0]?.[0])).toBe(`${BASE}/v1/team`);
    expect(r.source).toBe("live");
    expect(r.data).toEqual(VIEW);
  });

  it("TEAM_WEB_getTeamLive_unreadable_body_is_a_retryable_error_not_a_team", async () => {
    const { api } = apiWith(() => json({ version: 1 }));
    await expect(api.getTeamLive()).rejects.toMatchObject({ retryable: true });
  });

  it("TEAM_WEB_without_a_base_url_nothing_is_fetched_and_it_is_NotBuilt", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const api = createLiveApi();
    await expect(api.getTeamLive()).rejects.toBeInstanceOf(NotBuilt);
    await expect(api.writeTeam({ kind: "remove", id: "u2" })).rejects.toBeInstanceOf(NotBuilt);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("TEAM_WEB_the_fixture_api_answers_null_and_writes_nothing", async () => {
    const api = createFixtureApi();
    expect(await api.getTeamLive()).toEqual({ data: null, source: "fixture" });
    expect(await api.writeTeam({ kind: "remove", id: "u2" })).toEqual({
      data: null,
      source: "fixture",
    });
  });
});

describe("TEAM_WEB_live_api: the six Owner-only writes", () => {
  const cases: [string, Parameters<ReturnType<typeof createLiveApi>["writeTeam"]>[0], string, string, unknown][] = [
    ["role", { kind: "role", id: "u2", role: "Approver" }, "PUT", "/v1/team/members/u2/role", { role: "Approver" }],
    ["limit", { kind: "limit", id: "u2", limitMinor: 700 }, "PUT", "/v1/team/members/u2/limit", { limit_minor: 700 }],
    ["limit_none", { kind: "limit", id: "u2", limitMinor: null }, "PUT", "/v1/team/members/u2/limit", { limit_minor: null }],
    ["remove", { kind: "remove", id: "u2" }, "DELETE", "/v1/team/members/u2", undefined],
    ["switch", { kind: "switch", key: "weekend", on: true }, "PUT", "/v1/team/switches/weekend", { on: true }],
    ["tool", { kind: "tool", connector: "gmail", level: "read" }, "PUT", "/v1/team/tools/gmail", { level: "read" }],
  ];
  for (const [name, op, method, path, body] of cases) {
    it(`TEAM_WEB_writeTeam_${name}_sends_${method}_${path.replaceAll("/", "_")}`, async () => {
      const { fetchSpy, api } = apiWith(() => json(VIEW));
      const r = await api.writeTeam(op);
      const [url, init] = fetchSpy.mock.calls[0] ?? [];
      expect(String(url)).toBe(`${BASE}${path}`);
      expect(init?.method).toBe(method);
      expect(init?.body === undefined ? undefined : JSON.parse(String(init.body))).toEqual(body);
      expect(r).toEqual({ data: VIEW, source: "live" });
    });
  }

  it("TEAM_WEB_writeTeam_invite_posts_then_reads_the_team_again", async () => {
    const calls: string[] = [];
    const fetchSpy = vi.fn(async (u: string | URL | Request, i?: RequestInit) => {
      calls.push(`${i?.method ?? "GET"} ${String(u).replace(BASE, "")}`);
      return i?.method === "POST" ? json({ invite_id: "inv_9" }, 201) : json(VIEW);
    });
    const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
    const r = await api.writeTeam({ kind: "invite", email: "a@b.co", role: "Member" });
    expect(calls).toEqual(["POST /v1/team/invites", "GET /v1/team"]);
    expect(r.data).toEqual(VIEW);
  });

  it("TEAM_WEB_writeTeam_ids_are_path_encoded", async () => {
    const { fetchSpy, api } = apiWith(() => json(VIEW));
    await api.writeTeam({ kind: "remove", id: "a/b c" });
    expect(String(fetchSpy.mock.calls[0]?.[0])).toBe(`${BASE}/v1/team/members/a%2Fb%20c`);
  });
});

describe("TEAM_WEB_errors: every outcome has a plain sentence", () => {
  const statusOf = async (status: number, body: unknown = { detail: "x" }) => {
    const { api } = apiWith(() => json(body, status));
    try {
      await api.writeTeam({ kind: "remove", id: "u2" });
    } catch (e) {
      return e;
    }
    throw new Error("expected a failure");
  };

  it("TEAM_WEB_error_text_per_status", async () => {
    expect(teamErrorText(await statusOf(401))).toMatch(/sign in/i);
    expect(teamErrorText(await statusOf(403))).toMatch(/Owner/);
    expect(teamErrorText(await statusOf(404))).toMatch(/no longer/);
    expect(teamErrorText(await statusOf(409))).toMatch(/Someone else changed the team/);
    expect(teamErrorText(await statusOf(422, { detail: "Pick Owner, Approver, Member or Viewer." }))).toBe(
      "Pick Owner, Approver, Member or Viewer.",
    );
    const none = teamErrorText(await statusOf(503, { detail: "not_configured" }));
    expect(none).toBe("Team controls are not set up on this install yet.");
    expect(none).not.toContain("not_configured");
  });

  it("TEAM_WEB_replay_only_keeps_the_replay_only_sentence", async () => {
    const e = await statusOf(503, { replay_only: true });
    expect(e).toBeInstanceOf(TiloApiError);
    expect(teamErrorText(e)).toMatch(/Live models are unavailable/);
  });
});

describe("TEAM_WEB_applyOp: the optimistic copy", () => {
  it("TEAM_WEB_applyOp_changes_only_what_the_write_changes", () => {
    const v = VIEW as Parameters<typeof applyOp>[0];
    expect(applyOp(v, { kind: "role", id: "u2", role: "Viewer" }).members[1]?.role).toBe("Viewer");
    expect(applyOp(v, { kind: "remove", id: "u2" }).members).toHaveLength(1);
    expect(applyOp(v, { kind: "switch", key: "weekend", on: true }).switches[1]?.on).toBe(true);
    expect(applyOp(v, { kind: "tool", connector: "gmail", level: "off" }).tools[0]?.level).toBe("off");
    expect(applyOp(v, { kind: "invite", email: "x@y.co", role: "Member" })).toBe(v);
    expect(v.members[1]?.role).toBe("Member"); // the input is not changed
  });
});
