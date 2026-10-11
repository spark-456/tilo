import { describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { createLiveApi } from "./liveApi";

const make = (body: unknown, status = 200) => {
  const fetcher = vi.fn<typeof fetch>(
    async () =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
  );
  return { api: createLiveApi({ baseUrl: "https://api.example.test", fetch: fetcher }), fetcher };
};

describe("FR_TEAM_01 LIVE_GAPS_1A directory", () => {
  it("FR_TEAM_01 maps a member projection without inventing fields", async () => {
    const { api, fetcher } = make({
      you: "u_self",
      people: [{ id: "u_peer", display_name: "Peer" }],
    });
    const result = await api.getTeam();
    expect(result.source).toBe("live");
    expect(result.data.people).toEqual([
      {
        id: "u_peer",
        name: "Peer",
        email: null,
        dept: null,
        role: null,
        active: null,
        c: null,
        memberships: null,
        you: false,
      },
    ]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(String(fetcher.mock.calls[0]?.[0])).toBe("https://api.example.test/v1/people");
  });
  it("FR_TEAM_01 maps owner visibility and the caller's full row", async () => {
    const { api } = make({
      you: "u_self",
      people: [
        {
          id: "u_self",
          display_name: "Self",
          email: "self@example.test",
          org_role: "owner",
          memberships: [],
        },
        {
          id: "u_peer",
          display_name: "Peer",
          org_role: "member",
          memberships: [
            { team: "t_ops", assigned_by: { by: "u_self", at: "2026-10-09T00:00:00.000Z" } },
          ],
        },
      ],
    });
    const { data } = await api.getTeam();
    expect(data.people[0]).toMatchObject({
      you: true,
      role: "Owner",
      email: "self@example.test",
      memberships: [],
    });
    expect(data.people[1]).toMatchObject({ role: "Member", email: null, memberships: ["t_ops"] });
  });
  it.each([404, 503])("LIVE_GAPS_1A preserves the HTTP error %i", async (status) => {
    const { api } = make({ detail: "unavailable" }, status);
    await expect(api.getTeam()).rejects.toMatchObject({ status });
  });
  it.each([
    {},
    { you: "u_self", people: [{ id: "u_peer" }] },
    { you: "u_self", people: [{ id: "u_peer", display_name: "Peer", memberships: [null] }] },
  ])("LIVE_GAPS_1A refuses an unreadable reply %j", async (body) => {
    await expect(make(body).api.getTeam()).rejects.toBeInstanceOf(TiloApiError);
  });
});
