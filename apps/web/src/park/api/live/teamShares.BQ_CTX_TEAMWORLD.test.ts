// BQ-CTX-TEAMWORLD (ADR-0040, FR-TEAM-01..06): the strict readers of the team-sharing routes and the one write.
import { describe, expect, it, vi } from "vitest";
import { HttpClient, TiloApiError } from "../../../api/http";
import {
  itemsFromBody,
  readShares,
  setShare,
  sharedWorldFromBody,
  sharesFromBody,
} from "./teamShares";

const W = "w_launch";
const share = (over: Record<string, unknown> = {}) => ({
  team: "tm_launch",
  in_force: true,
  reason: null,
  granted_at: "2026-10-10T09:00:00.000Z",
  ...over,
});
const item = (over: Record<string, unknown> = {}) => ({
  id: "wi_1",
  title: "Book the venue",
  status: "open",
  due: null,
  owner: "u_ben",
  world_id: W,
  ...over,
});
const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const clientOf = (fetch: typeof globalThis.fetch) =>
  new HttpClient({ baseUrl: "https://api.test", fetch });

describe("BQ_CTX_TEAMWORLD shares reply", () => {
  it("FR_TEAM_01 reads rows with a reason only when not in force", () => {
    const rows = sharesFromBody(
      {
        world_id: W,
        shares: [share(), share({ team: "tm_ops", in_force: false, reason: "not_yet" })],
      },
      W,
    );
    expect(rows?.map((r) => [r.team, r.inForce, r.reason])).toEqual([
      ["tm_launch", true, null],
      ["tm_ops", false, "not_yet"],
    ]);
  });

  it("FR_TEAM_01 refuses another world, an unknown reason word and an in-force row with a reason", () => {
    expect(sharesFromBody({ world_id: "w_other", shares: [] }, W)).toBeNull();
    expect(
      sharesFromBody({ world_id: W, shares: [share({ in_force: false, reason: "because" })] }, W),
    ).toBeNull();
    expect(sharesFromBody({ world_id: W, shares: [share({ reason: "revoked" })] }, W)).toBeNull();
    expect(
      sharesFromBody({ world_id: W, shares: [share({ in_force: false, reason: null })] }, W),
    ).toBeNull();
    expect(sharesFromBody({ world_id: W }, W)).toBeNull();
  });

  it("FR_TEAM_02 a revoked share is not a share the dialog shows", async () => {
    const fetch = vi.fn(async () =>
      reply({
        world_id: W,
        shares: [share({ in_force: false, reason: "revoked" }), share({ team: "tm_ops" })],
      }),
    );
    expect((await readShares(clientOf(fetch), W)).map((s) => s.team)).toEqual(["tm_ops"]);
  });
});

describe("BQ_CTX_TEAMWORLD items and world replies", () => {
  it("FR_TEAM_05 reads open and done rows and the truncation flag, and nothing else", () => {
    const got = itemsFromBody(
      {
        world_id: W,
        items: [item(), item({ id: "wi_2", status: "done", due: "2026-10-20" })],
        truncated: true,
      },
      W,
    );
    expect(got?.truncated).toBe(true);
    expect(got?.items.map((i) => [i.id, i.status, i.due])).toEqual([
      ["wi_1", "open", null],
      ["wi_2", "done", "2026-10-20"],
    ]);
  });

  it("FR_TEAM_05 refuses a row of another world, a proposed row and a row with no owner", () => {
    expect(itemsFromBody({ world_id: W, items: [item({ world_id: "w_x" })] }, W)).toBeNull();
    expect(itemsFromBody({ world_id: W, items: [item({ status: "proposed" })] }, W)).toBeNull();
    expect(itemsFromBody({ world_id: W, items: [item({ owner: "" })] }, W)).toBeNull();
  });

  it("FR_TEAM_03 reads the districts a Viewer sees and says when some are hidden", () => {
    const world = sharedWorldFromBody(
      {
        world_id: W,
        districts: [{ id: "D1", name: "Design", summary: "s" }],
        has_hidden_districts: true,
      },
      W,
    );
    expect(world).toEqual({
      districts: [{ id: "D1", name: "Design", summary: "s" }],
      hasHiddenDistricts: true,
    });
    expect(sharedWorldFromBody({ world_id: W, districts: [{ id: "D1" }] }, W)).toBeNull();
  });
});

describe("BQ_CTX_TEAMWORLD setShare", () => {
  it("FR_TEAM_01 a grant is a PUT and a revoke a DELETE of the encoded team, with no body", async () => {
    const fetch = vi.fn(async (_u: RequestInfo | URL, init?: RequestInit) =>
      reply({
        world_id: W,
        team: "tm_a",
        state: init?.method === "PUT" ? "on" : "off",
        in_force: true,
      }),
    );
    await setShare(clientOf(fetch), W, "tm_a", true);
    await setShare(clientOf(fetch), W, "tm_a", false);
    expect(fetch.mock.calls.map((c) => [c[0], c[1]?.method, c[1]?.body])).toEqual([
      ["https://api.test/worlds/w_launch/team-shares/tm_a", "PUT", undefined],
      ["https://api.test/worlds/w_launch/team-shares/tm_a", "DELETE", undefined],
    ]);
  });

  it("FR_TEAM_01 an answer that does not name this change is an unreadable reply, not success", async () => {
    const wrongState = vi.fn(async () =>
      reply({ world_id: W, team: "tm_a", state: "off", in_force: false }),
    );
    await expect(setShare(clientOf(wrongState), W, "tm_a", true)).rejects.toBeInstanceOf(
      TiloApiError,
    );
    const otherTeam = vi.fn(async () =>
      reply({ world_id: W, team: "tm_b", state: "on", in_force: true }),
    );
    await expect(setShare(clientOf(otherTeam), W, "tm_a", true)).rejects.toBeInstanceOf(
      TiloApiError,
    );
  });

  it("FR_TEAM_01 the recorded sample project is never sent a share", async () => {
    const fetch = vi.fn(async () => reply({}));
    await expect(
      setShare(clientOf(fetch), "w_sample_village_basic", "tm_a", true),
    ).rejects.toMatchObject({
      code: "sample_is_a_replay",
    });
    expect(fetch).not.toHaveBeenCalled();
  });
});
